"""Hybrid Isolation Forest + Random Forest training, evaluation, and MongoDB scoring."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import joblib
import numpy as np
import pandas as pd
import shap
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import (
    classification_report,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from database import bulk_update_consumer_scores, load_consumers_dataframe, ping_db


PROJECT_ROOT = Path(__file__).resolve().parent
MODELS_DIR = PROJECT_ROOT / "models"
HYBRID_MODEL_PATH = MODELS_DIR / "hybrid_models.pkl"

FEATURE_COLUMNS = [
    "latest_kwh",
    "avg_6m",
    "pct_change_from_avg",
    "std_dev",
    "z_score",
    "peer_ratio",
    "sanctioned_load",
    "load_utilization",
]


def assign_status(score: int) -> str:
    """Map integer 0-100 risk score to operational inspection status."""
    if score >= 70:
        return "Inspect"
    if score >= 40:
        return "Watchlist"
    return "Normal"


def normalize_iso_scores(raw_inverted: np.ndarray, min_s: float, max_s: float) -> np.ndarray:
    """Normalize inverted IsolationForest scores to 0-100 using fixed bounds."""
    if max_s > min_s:
        scaled = ((raw_inverted - min_s) / (max_s - min_s)) * 100.0
    else:
        scaled = np.zeros_like(raw_inverted)
    return np.clip(scaled, 0.0, 100.0)


def extract_theft_shap(explainer: shap.TreeExplainer, X_scaled: np.ndarray) -> np.ndarray:
    """Extract class-1 (Theft) SHAP values from a binary RandomForest TreeExplainer."""
    raw = explainer.shap_values(X_scaled)
    if isinstance(raw, list):
        return np.asarray(raw[1], dtype=np.float64)
    arr = np.asarray(raw, dtype=np.float64)
    if arr.ndim == 3:
        return arr[:, :, 1]
    return arr


def evaluate_holdout(X_labeled: np.ndarray, y_labeled: np.ndarray) -> dict[str, float]:
    """Evaluate the hybrid ensemble on a strict 20% holdout split without data leakage."""
    X_train, X_test, y_train, y_test = train_test_split(
        X_labeled,
        y_labeled,
        test_size=0.2,
        stratify=y_labeled,
        random_state=42,
    )

    eval_scaler = StandardScaler()
    X_train_scaled = eval_scaler.fit_transform(X_train)
    X_test_scaled = eval_scaler.transform(X_test)

    eval_iso = IsolationForest(
        n_estimators=200,
        contamination=0.05,
        random_state=42,
    )
    eval_iso.fit(X_train_scaled)

    train_inv = -eval_iso.decision_function(X_train_scaled)
    min_s = float(train_inv.min())
    max_s = float(train_inv.max())

    eval_rf = RandomForestClassifier(
        n_estimators=200,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    eval_rf.fit(X_train_scaled, y_train)

    test_iso_norm = normalize_iso_scores(-eval_iso.decision_function(X_test_scaled), min_s, max_s)
    test_rf_prob = eval_rf.predict_proba(X_test_scaled)[:, 1]
    blended_score = 0.4 * test_iso_norm + 0.6 * (test_rf_prob * 100.0)

    y_pred = (blended_score >= 40.0).astype(int)

    precision = float(precision_score(y_test, y_pred, zero_division=0))
    recall = float(recall_score(y_test, y_pred, zero_division=0))
    f1 = float(f1_score(y_test, y_pred, zero_division=0))
    roc_auc = float(roc_auc_score(y_test, blended_score / 100.0))

    print("\n=== Holdout Test Split Evaluation (20% Stratified, Threshold >= 40) ===")
    print(classification_report(y_test, y_pred, target_names=["Normal (0)", "Theft (1)"], digits=4))
    print(f"ROC-AUC Score: {roc_auc:.4f}\n")

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1_score": round(f1, 4),
        "roc_auc": round(roc_auc, 4),
        "test_samples": int(len(y_test)),
    }


def run_training() -> dict[str, Any]:
    """Load MongoDB consumers, train hybrid ensemble, compute SHAP, and update MongoDB."""
    if not ping_db():
        raise RuntimeError("MongoDB connection failed.")

    df = load_consumers_dataframe()
    if df.empty:
        raise RuntimeError("No consumer records found in MongoDB. Run prepare_data.py first.")

    missing = [col for col in FEATURE_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Missing required behavioral features in MongoDB: {missing}")

    print(f"Loaded {len(df):,} consumer documents from MongoDB.")

    X_all = df[FEATURE_COLUMNS].to_numpy(dtype=float)

    labeled_mask = df["ground_truth"].notna()
    labeled_df = df.loc[labeled_mask]
    if labeled_df.empty or labeled_df["ground_truth"].nunique() < 2:
        raise RuntimeError("Need both Normal (0) and Theft (1) ground_truth labels for RF training.")

    X_labeled = labeled_df[FEATURE_COLUMNS].to_numpy(dtype=float)
    y_labeled = labeled_df["ground_truth"].astype(int).to_numpy()

    metrics = evaluate_holdout(X_labeled, y_labeled)

    # Fit production scaler and models on latest data
    scaler = StandardScaler()
    X_all_scaled = scaler.fit_transform(X_all)
    X_labeled_scaled = scaler.transform(X_labeled)

    iso_forest = IsolationForest(
        n_estimators=200,
        contamination=0.05,
        random_state=42,
    )
    iso_forest.fit(X_all_scaled)

    all_inv = -iso_forest.decision_function(X_all_scaled)
    min_s = float(all_inv.min())
    max_s = float(all_inv.max())
    iso_norm_all = normalize_iso_scores(all_inv, min_s, max_s)

    rf_clf = RandomForestClassifier(
        n_estimators=200,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    rf_clf.fit(X_labeled_scaled, y_labeled)

    rf_prob_all = rf_clf.predict_proba(X_all_scaled)[:, 1]
    blended_all = 0.4 * iso_norm_all + 0.6 * (rf_prob_all * 100.0)
    risk_scores = np.clip(np.rint(blended_all), 0, 100).astype(int)
    statuses = [assign_status(int(s)) for s in risk_scores]

    print("Computing SHAP TreeExplainer values for all consumers...")
    explainer = shap.TreeExplainer(rf_clf)
    shap_matrix = extract_theft_shap(explainer, X_all_scaled)

    updates = []
    consumer_ids = df["consumer_id"].tolist()
    for idx, cid in enumerate(consumer_ids):
        shap_dict = {
            feat: round(float(shap_matrix[idx, col_idx]), 5)
            for col_idx, feat in enumerate(FEATURE_COLUMNS)
        }
        updates.append(
            {
                "consumer_id": cid,
                "risk_score": int(risk_scores[idx]),
                "status": statuses[idx],
                "shap_values": shap_dict,
            }
        )

    updated_count = bulk_update_consumer_scores(updates, batch_size=5000)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    bundle = {
        "scaler": scaler,
        "iso_forest": iso_forest,
        "rf_clf": rf_clf,
        "min_s": min_s,
        "max_s": max_s,
        "feature_columns": FEATURE_COLUMNS,
        "metrics": metrics,
    }
    joblib.dump(bundle, HYBRID_MODEL_PATH)

    status_series = pd.Series(statuses).value_counts().reindex(
        ["Inspect", "Watchlist", "Normal"], fill_value=0
    )
    print("Updated MongoDB risk status distribution:")
    for name, count in status_series.items():
        print(f"  {name:10s}: {count:,} ({count / len(df) * 100:.2f}%)")

    print(f"Bulk-updated {updated_count:,} MongoDB consumer documents.")
    print(f"Saved hybrid model bundle -> {HYBRID_MODEL_PATH}")

    return {
        "total_consumers": int(len(df)),
        "labeled_consumers": int(len(labeled_df)),
        "metrics": metrics,
        "status_counts": {k: int(v) for k, v in status_series.items()},
    }


def main() -> None:
    run_training()


if __name__ == "__main__":
    main()
