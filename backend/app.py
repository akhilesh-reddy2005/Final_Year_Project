"""Pure Flask REST API backend for Karnataka ESCOM Theft Risk Monitor."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from flask import Flask, jsonify, request
import joblib
import numpy as np
import shap
from database import (
    get_consumer_by_id,
    get_distinct_zones_and_categories,
    get_latest_inspection,
    get_next_consumer_id,
    get_peer_medians,
    get_zone_tariff_analytics,
    insert_consumer,
    log_meter_reading,
    ping_db,
    query_consumers,
    record_inspection,
    search_consumer_ids,
    update_consumer_reading,
)
from train import assign_status, extract_theft_shap, normalize_iso_scores, run_training


PROJECT_ROOT = Path(__file__).resolve().parent
HYBRID_MODEL_PATH = PROJECT_ROOT / "models" / "hybrid_models.pkl"

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

FEATURE_LABELS = {
    "latest_kwh": "Latest Monthly kWh",
    "avg_6m": "6M Baseline Avg",
    "pct_change_from_avg": "% Change vs 6M Avg",
    "std_dev": "Std Dev",
    "z_score": "Consumption Z-Score",
    "peer_ratio": "Peer Ratio",
    "sanctioned_load": "Sanctioned Load",
    "load_utilization": "Load Utilization",
}

AREA_ZONES = [
    "BESCOM - Bengaluru South",
    "BESCOM - Bengaluru East",
    "MESCOM - Mangaluru",
    "HESCOM - Hubballi",
    "CESC - Mysuru",
    "GESCOM - Kalaburagi",
]

CATEGORIES = ["LT-2a Residential", "LT-3 Commercial"]
STATUS_OPTIONS = ["Flagged", "Inspect", "Watchlist", "Normal", "All"]
MAX_TABLE_ROWS = 500
DATALIST_SEED_COUNT = 250


def format_feature_value(feat: str, value: float) -> str:
    """Format a behavioral feature with domain units for display."""
    if feat in ("latest_kwh", "avg_6m", "std_dev"):
        return f"{value:,.1f} kWh"
    if feat == "pct_change_from_avg":
        return f"{value * 100.0:+.1f}%"
    if feat == "z_score":
        return f"{value:+.2f} \u03c3"
    if feat == "peer_ratio":
        return f"{value:.2f}x"
    if feat == "sanctioned_load":
        return f"{value:.2f} kW"
    if feat == "load_utilization":
        return f"{value * 100.0:.1f}%"
    return f"{value:.2f}"


def estimate_sanctioned_load(baseline_kwh: float, category: str) -> float:
    """Estimate sanctioned load (kW) from baseline kWh and tariff category."""
    boost = 1.25 if category == "LT-3 Commercial" else 1.0
    load_kw = (1.1 + (baseline_kwh / 240.0)) * boost
    return round(float(np.clip(load_kw, 1.0, 25.0)), 2)


def build_shap_contributions(feature_values: dict[str, float], shap_dict: dict[str, float]) -> list[dict]:
    """Convert stored/computed theft SHAP values into ordered chart entries."""
    return [
        {
            "feature": feat,
            "label": FEATURE_LABELS[feat],
            "value": float(feature_values[feat]),
            "formatted_value": format_feature_value(feat, float(feature_values[feat])),
            "shap_value": float(shap_dict.get(feat, 0.0)),
            "risk_contribution": float(shap_dict.get(feat, 0.0)),
        }
        for feat in FEATURE_COLUMNS
    ]


def load_hybrid_bundle() -> tuple[dict, shap.TreeExplainer]:
    """Load the hybrid model bundle and initialize TreeExplainer on the Random Forest."""
    if not HYBRID_MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Missing {HYBRID_MODEL_PATH}. Run prepare_data.py and train.py first."
        )
    bundle = joblib.load(HYBRID_MODEL_PATH)
    explainer = shap.TreeExplainer(bundle["rf_clf"])
    return bundle, explainer


app = Flask(__name__)
MODEL_LOCK = Lock()

ping_db()
HYBRID_BUNDLE, EXPLAINER = load_hybrid_bundle()
PEER_LOOKUP = get_peer_medians()


@app.after_request
def add_cors_headers(response):
    """Allow Vite dev server (localhost:5173) to call Flask API routes cleanly."""
    if request.path.startswith("/api/"):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


def score_live_features(feature_values: dict[str, float]) -> tuple[int, str, dict[str, float]]:
    """Score 8 behavioral features using the hybrid IsolationForest + RandomForest ensemble."""
    X_raw = np.array([[feature_values[col] for col in FEATURE_COLUMNS]], dtype=float)
    with MODEL_LOCK:
        scaler = HYBRID_BUNDLE["scaler"]
        iso_forest = HYBRID_BUNDLE["iso_forest"]
        rf_clf = HYBRID_BUNDLE["rf_clf"]
        min_s = float(HYBRID_BUNDLE["min_s"])
        max_s = float(HYBRID_BUNDLE["max_s"])

        X_scaled = scaler.transform(X_raw)
        iso_inv = -iso_forest.decision_function(X_scaled)
        iso_norm = float(normalize_iso_scores(iso_inv, min_s, max_s)[0])
        rf_prob = float(rf_clf.predict_proba(X_scaled)[0, 1])

        blended = 0.4 * iso_norm + 0.6 * (rf_prob * 100.0)
        risk_score = int(np.clip(np.rint(blended), 0, 100))
        status = assign_status(risk_score)

        shap_row = extract_theft_shap(EXPLAINER, X_scaled)[0]

    shap_dict = {
        feat: round(float(shap_row[idx]), 5)
        for idx, feat in enumerate(FEATURE_COLUMNS)
    }
    return risk_score, status, shap_dict


@app.route("/", methods=["GET"])
def api_root():
    """Return REST API metadata and available endpoints."""
    return jsonify(
        {
            "service": "BESCOM GridGuard AI Backend API",
            "status": "running",
            "endpoints": [
                "GET /api/health",
                "GET /api/dashboard",
                "GET /api/consumers",
                "GET /api/consumer/<consumer_id>",
                "POST /api/predict_reading",
                "POST /api/add_consumer",
                "POST /api/verify_inspection",
                "POST /api/retrain",
            ],
        }
    )


@app.route("/api/health", methods=["GET"])
def health_check():
    """Verify MongoDB connectivity and loaded model readiness."""
    return jsonify({"status": "ok", "mongodb": ping_db()})


@app.route("/api/dashboard", methods=["GET"])
def get_dashboard_data():
    """Return filtered consumers, KPIs, model metrics, and zone analytics for React."""
    db_zones, db_categories = get_distinct_zones_and_categories()
    zones = sorted(set(AREA_ZONES).union(db_zones))
    categories = sorted(set(CATEGORIES).union(db_categories))

    selected_zone = request.args.get("zone", "All")
    selected_category = request.args.get("category", "All")
    selected_status = request.args.get("status", "Flagged")

    if selected_zone != "All" and selected_zone not in zones:
        selected_zone = "All"
    if selected_category != "All" and selected_category not in categories:
        selected_category = "All"
    if selected_status not in STATUS_OPTIONS:
        selected_status = "Flagged"

    rows, total_matching, kpis = query_consumers(
        zone=selected_zone,
        category=selected_category,
        status=selected_status,
        limit=MAX_TABLE_ROWS,
    )
    seed_ids = search_consumer_ids("", limit=DATALIST_SEED_COUNT)
    next_consumer_id = get_next_consumer_id()
    zone_analytics = get_zone_tariff_analytics()

    return jsonify(
        {
            "zones": zones,
            "categories": categories,
            "status_options": STATUS_OPTIONS,
            "selected_zone": selected_zone,
            "selected_category": selected_category,
            "selected_status": selected_status,
            "kpis": kpis,
            "rows": rows,
            "total_matching": total_matching,
            "seed_consumer_ids": seed_ids,
            "next_consumer_id": next_consumer_id,
            "model_metrics": HYBRID_BUNDLE.get("metrics", {}),
            "zone_analytics": zone_analytics,
        }
    )


@app.route("/api/consumers", methods=["GET"])
def search_consumers():
    """Return matching consumer IDs from MongoDB for live autocomplete."""
    query = request.args.get("q", "")
    return jsonify({"consumer_ids": search_consumer_ids(query, limit=50)})


@app.route("/api/consumer/<consumer_id>", methods=["GET"])
def get_consumer_explanation(consumer_id: str):
    """Return a consumer's behavioral metrics, inspection status, and SHAP attributions."""
    doc = get_consumer_by_id(consumer_id)
    if doc is None:
        return jsonify({"error": f"Consumer '{consumer_id}' not found."}), 404

    peer_median_kwh, peer_median_std = PEER_LOOKUP.get(
        (str(doc["area_zone"]), str(doc["category"])),
        (float(doc["latest_kwh"]), float(doc["std_dev"])),
    )

    features = {feat: float(doc.get(feat, 0.0)) for feat in FEATURE_COLUMNS}
    shap_dict = {
        feat: float(doc.get("shap_values", {}).get(feat, 0.0))
        for feat in FEATURE_COLUMNS
    }
    latest_inspection = get_latest_inspection(str(doc["consumer_id"]))

    return jsonify(
        {
            "consumer_id": str(doc["consumer_id"]),
            "area_zone": str(doc["area_zone"]),
            "category": str(doc["category"]),
            "risk_score": int(doc["risk_score"]),
            "status": str(doc["status"]),
            "ground_truth": doc.get("ground_truth"),
            "latest_inspection": latest_inspection,
            "features": features,
            "peer_stats": {
                "peer_median_kwh": peer_median_kwh,
                "peer_median_std": peer_median_std,
            },
            "shap_values": shap_dict,
            "shap_contributions": build_shap_contributions(features, shap_dict),
        }
    )


@app.route("/api/predict_reading", methods=["POST"])
def predict_reading():
    """Score a live meter reading, log to meter_readings, and update MongoDB consumer."""
    payload = request.get_json(silent=True) or {}
    raw_id = str(payload.get("consumer_id", "")).strip()
    if not raw_id:
        return jsonify({"error": "Please enter a valid Consumer ID."}), 400

    try:
        units_used = float(payload.get("units_used"))
    except (TypeError, ValueError):
        return jsonify({"error": "Current Units Used (kWh) must be a valid number."}), 400

    if not np.isfinite(units_used) or units_used < 0:
        return jsonify({"error": "Current Units Used (kWh) must be 0 or greater."}), 400

    save_record = bool(payload.get("save_record", True))

    doc = get_consumer_by_id(raw_id)
    if doc is None:
        return jsonify({"error": f"Consumer '{raw_id}' not found."}), 404

    consumer_id = str(doc["consumer_id"])
    area_zone = str(doc["area_zone"])
    category = str(doc["category"])
    avg_6m = float(doc["avg_6m"])
    old_std = float(doc["std_dev"])
    sanctioned_load = float(doc.get("sanctioned_load", estimate_sanctioned_load(avg_6m, category)))

    peer_median_kwh, peer_median_std = PEER_LOOKUP.get(
        (area_zone, category),
        (avg_6m, old_std),
    )

    latest_kwh = units_used
    pct_change_from_avg = (units_used - avg_6m) / (avg_6m + 1e-5)
    std_dev = 0.7 * old_std + 0.3 * abs(units_used - avg_6m)
    z_score = (units_used - avg_6m) / (std_dev + 1.0)
    peer_ratio = units_used / (peer_median_kwh + 1e-5)
    load_utilization = units_used / (sanctioned_load * 720.0 + 1e-5)

    features = {
        "latest_kwh": round(latest_kwh, 2),
        "avg_6m": round(avg_6m, 2),
        "pct_change_from_avg": round(pct_change_from_avg, 4),
        "std_dev": round(std_dev, 2),
        "z_score": round(z_score, 4),
        "peer_ratio": round(peer_ratio, 4),
        "sanctioned_load": round(sanctioned_load, 2),
        "load_utilization": round(load_utilization, 4),
    }

    risk_score, status, shap_dict = score_live_features(features)

    log_meter_reading(
        consumer_id=consumer_id,
        units_kwh=units_used,
        risk_score=risk_score,
        status=status,
    )

    if save_record:
        update_consumer_reading(
            consumer_id,
            {
                **features,
                "risk_score": risk_score,
                "status": status,
                "shap_values": shap_dict,
            },
        )

    return jsonify(
        {
            "consumer_id": consumer_id,
            "area_zone": area_zone,
            "category": category,
            "avg_6m": features["avg_6m"],
            "units_used": features["latest_kwh"],
            "pct_change": round(pct_change_from_avg * 100.0, 2),
            "peer_ratio": features["peer_ratio"],
            "peer_median_kwh": round(peer_median_kwh, 2),
            "peer_median_std": round(peer_median_std, 2),
            "risk_score": risk_score,
            "status": status,
            "saved": save_record,
            "features": features,
            "shap_values": shap_dict,
            "shap_contributions": build_shap_contributions(features, shap_dict),
        }
    )


@app.route("/api/add_consumer", methods=["POST"])
def add_consumer():
    """Register a new consumer, score all 8 behavioral features, and insert into MongoDB."""
    payload = request.get_json(silent=True) or {}
    area_zone = str(payload.get("area_zone", "")).strip()
    category = str(payload.get("category", "")).strip()

    db_zones, db_categories = get_distinct_zones_and_categories()
    valid_zones = set(AREA_ZONES).union(db_zones)
    valid_categories = set(CATEGORIES).union(db_categories)

    if area_zone not in valid_zones:
        return jsonify({"error": "Please select a valid ESCOM Area Zone."}), 400
    if category not in valid_categories:
        return jsonify({"error": "Please select a valid Tariff Category."}), 400

    try:
        baseline_kwh = float(payload.get("baseline_kwh"))
    except (TypeError, ValueError):
        return jsonify({"error": "Baseline Monthly Consumption (kWh) must be a valid number."}), 400

    if not np.isfinite(baseline_kwh) or baseline_kwh <= 0:
        return jsonify({"error": "Baseline Monthly Consumption (kWh) must be greater than 0."}), 400

    raw_id = str(payload.get("consumer_id", "")).strip()
    if raw_id:
        consumer_id = raw_id.upper()
        if get_consumer_by_id(consumer_id) is not None:
            next_free = get_next_consumer_id()
            return jsonify(
                {
                    "error": (
                        f"Consumer ID '{consumer_id}' already exists. "
                        f"Leave Consumer ID blank to auto-generate {next_free}, "
                        f"or enter an unused ID (e.g., {next_free} or KA-60001)."
                    )
                }
            ), 400
    else:
        consumer_id = get_next_consumer_id()

    peer_median_kwh, _ = PEER_LOOKUP.get(
        (area_zone, category),
        (baseline_kwh, baseline_kwh * 0.08),
    )

    sanctioned_load = estimate_sanctioned_load(baseline_kwh, category)
    std_dev = baseline_kwh * 0.08
    features = {
        "latest_kwh": round(baseline_kwh, 2),
        "avg_6m": round(baseline_kwh, 2),
        "pct_change_from_avg": 0.0,
        "std_dev": round(std_dev, 2),
        "z_score": 0.0,
        "peer_ratio": round(baseline_kwh / (peer_median_kwh + 1e-5), 4),
        "sanctioned_load": sanctioned_load,
        "load_utilization": round(baseline_kwh / (sanctioned_load * 720.0 + 1e-5), 4),
    }

    risk_score, status, shap_dict = score_live_features(features)

    doc = {
        "consumer_id": consumer_id,
        "area_zone": area_zone,
        "category": category,
        **features,
        "risk_score": risk_score,
        "status": status,
        "ground_truth": 0,
        "shap_values": shap_dict,
    }
    insert_consumer(doc)

    return jsonify(
        {
            **doc,
            "features": features,
            "shap_contributions": build_shap_contributions(features, shap_dict),
        }
    ), 201


@app.route("/api/verify_inspection", methods=["POST"])
def verify_inspection():
    """Record a field vigilance inspection outcome and update consumer ground_truth."""
    payload = request.get_json(silent=True) or {}
    consumer_id = str(payload.get("consumer_id", "")).strip().upper()
    outcome = str(payload.get("outcome", "")).strip()
    remarks = str(payload.get("remarks", "")).strip()

    if not consumer_id:
        return jsonify({"error": "Consumer ID is required."}), 400

    doc = get_consumer_by_id(consumer_id)
    if doc is None:
        return jsonify({"error": f"Consumer '{consumer_id}' not found."}), 404

    outcome_lower = outcome.lower()
    if outcome_lower in ("confirmed theft", "confirm theft", "theft", "1"):
        normalized_outcome = "Confirmed Theft"
        ground_truth = 1
    elif outcome_lower in ("false alarm", "mark false alarm", "normal", "0"):
        normalized_outcome = "False Alarm"
        ground_truth = 0
    else:
        return jsonify({"error": "Outcome must be 'Confirmed Theft' or 'False Alarm'."}), 400

    inspection = record_inspection(
        consumer_id=consumer_id,
        outcome=normalized_outcome,
        ground_truth=ground_truth,
        remarks=remarks,
    )
    return jsonify(
        {
            "consumer_id": consumer_id,
            "outcome": normalized_outcome,
            "ground_truth": ground_truth,
            "inspection": inspection,
        }
    )


@app.route("/api/retrain", methods=["POST"])
def retrain_model():
    """Retrain the hybrid ensemble on the latest MongoDB consumers and reload weights."""
    global HYBRID_BUNDLE, EXPLAINER, PEER_LOOKUP

    summary = run_training()
    new_bundle, new_explainer = load_hybrid_bundle()
    new_peers = get_peer_medians()

    with MODEL_LOCK:
        HYBRID_BUNDLE = new_bundle
        EXPLAINER = new_explainer
        PEER_LOOKUP = new_peers

    return jsonify(summary)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
