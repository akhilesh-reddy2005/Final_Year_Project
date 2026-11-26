"""Data inspection, 8 behavioral feature engineering, and MongoDB seeding."""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
from database import ping_db, seed_consumers


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
GENERATED_FILES = {"engineered_consumers.csv", "scored_consumers.csv"}

AREA_ZONES = [
    "BESCOM - Bengaluru South",
    "BESCOM - Bengaluru East",
    "MESCOM - Mangaluru",
    "HESCOM - Hubballi",
    "CESC - Mysuru",
    "GESCOM - Kalaburagi",
]

CATEGORIES = ["LT-2a Residential", "LT-3 Commercial"]
CATEGORY_WEIGHTS = [0.85, 0.15]

TAMPER_RATE = 0.05
RANDOM_SEED = 42


def locate_raw_csv(root_dir: Path = PROJECT_ROOT, data_dir: Path = DATA_DIR) -> Path:
    """Locate the raw input CSV file in the project root or data/ directory."""
    candidates: list[Path] = []
    for search_dir in (root_dir, data_dir):
        if search_dir.exists():
            csvs = sorted(
                p for p in search_dir.glob("*.csv")
                if p.is_file() and p.name.lower() not in GENERATED_FILES
            )
            candidates.extend(csvs)

    if not candidates:
        raise FileNotFoundError(f"No raw .csv file found in {root_dir} or {data_dir}.")
    return candidates[0]


def detect_consumption_column(df: pd.DataFrame) -> str:
    """Identify the monthly kWh/consumption column from the raw dataset."""
    normalized = {col: col.strip().lower().replace(" ", "_") for col in df.columns}
    exact_priority = [
        "monthly_kwh",
        "kwh",
        "monthlyhours",
        "monthly_hours",
        "monthly_consumption",
        "consumption",
        "units",
        "avg_kwh",
    ]
    for target in exact_priority:
        for orig_col, norm_col in normalized.items():
            if norm_col == target:
                return orig_col

    keywords = ("kwh", "consumption", "monthlyhour", "monthly_hour", "unit")
    for orig_col, norm_col in normalized.items():
        if any(kw in norm_col for kw in keywords):
            return orig_col

    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    if numeric_cols:
        return numeric_cols[-1]

    raise ValueError("Unable to detect a numeric monthly consumption column in the dataset.")


def clean_raw_dataset(df: pd.DataFrame, consumption_col: str) -> pd.DataFrame:
    """Remove duplicates and filter missing or invalid consumption entries."""
    initial_rows = len(df)
    dup_count = int(df.duplicated().sum())
    df_clean = df.drop_duplicates().copy()

    df_clean[consumption_col] = pd.to_numeric(df_clean[consumption_col], errors="coerce")
    invalid_mask = df_clean[consumption_col].isna() | (df_clean[consumption_col] <= 0)
    invalid_count = int(invalid_mask.sum())
    df_clean = df_clean.loc[~invalid_mask].reset_index(drop=True)

    print(
        f"Cleaning summary: initial={initial_rows:,}, duplicates_removed={dup_count:,}, "
        f"missing_or_invalid_removed={invalid_count:,}, retained={len(df_clean):,}"
    )
    return df_clean


def estimate_sanctioned_load(df_clean: pd.DataFrame, avg_6m: np.ndarray, categories: np.ndarray) -> np.ndarray:
    """Estimate sanctioned load (kW) from appliance counts and baseline kWh."""
    def col_or_zeros(name: str) -> np.ndarray:
        if name in df_clean.columns:
            return pd.to_numeric(df_clean[name], errors="coerce").fillna(0).to_numpy(dtype=float)
        return np.zeros(len(df_clean), dtype=float)

    ac = col_or_zeros("AirConditioner")
    pump = col_or_zeros("MotorPump")
    tv = col_or_zeros("Television")
    fridge = col_or_zeros("Refrigerator")

    commercial_boost = np.where(categories == "LT-3 Commercial", 1.25, 1.0)
    raw_load = (
        0.75
        + 0.45 * ac
        + 0.30 * pump
        + 0.04 * tv
        + 0.02 * fridge
        + (avg_6m / 240.0)
    ) * commercial_boost
    return np.round(np.clip(raw_load, 1.0, 25.0), 2)


def build_consumer_documents(df_clean: pd.DataFrame, consumption_col: str) -> list[dict]:
    """Compute 8 behavioral features, inject synthetic tampering, and format MongoDB documents."""
    rng = np.random.default_rng(RANDOM_SEED)
    n_rows = len(df_clean)

    consumer_ids = [f"KA-{10000 + i}" for i in range(n_rows)]
    area_zones = rng.choice(AREA_ZONES, size=n_rows, replace=True)
    categories = rng.choice(CATEGORIES, size=n_rows, replace=True, p=CATEGORY_WEIGHTS)

    avg_6m = df_clean[consumption_col].to_numpy(dtype=float)
    sanctioned_load = estimate_sanctioned_load(df_clean, avg_6m, categories)

    # Normal month-to-month fluctuation and baseline volatility
    normal_multiplier = rng.normal(loc=1.0, scale=0.08, size=n_rows).clip(0.75, 1.25)
    latest_kwh = avg_6m * normal_multiplier
    std_dev = avg_6m * rng.uniform(0.04, 0.12, size=n_rows)
    ground_truth = np.zeros(n_rows, dtype=int)

    # Inject synthetic meter tampering (55%-85% sudden drop + elevated volatility) into 5%
    n_tampered = max(1, int(round(TAMPER_RATE * n_rows)))
    tamper_indices = rng.choice(n_rows, size=n_tampered, replace=False)
    tamper_drop = rng.uniform(0.55, 0.85, size=n_tampered)
    latest_kwh[tamper_indices] = avg_6m[tamper_indices] * (1.0 - tamper_drop)
    std_dev[tamper_indices] = avg_6m[tamper_indices] * rng.uniform(0.28, 0.50, size=n_tampered)
    ground_truth[tamper_indices] = 1

    pct_change_from_avg = (latest_kwh - avg_6m) / (avg_6m + 1e-5)
    z_score = (latest_kwh - avg_6m) / (std_dev + 1.0)
    load_utilization = latest_kwh / (sanctioned_load * 720.0 + 1e-5)

    df_features = pd.DataFrame(
        {
            "consumer_id": consumer_ids,
            "area_zone": area_zones,
            "category": categories,
            "sanctioned_load": np.round(sanctioned_load, 2),
            "avg_6m": np.round(avg_6m, 2),
            "std_dev": np.round(std_dev, 2),
            "latest_kwh": np.round(latest_kwh, 2),
            "pct_change_from_avg": np.round(pct_change_from_avg, 4),
            "z_score": np.round(z_score, 4),
            "load_utilization": np.round(load_utilization, 4),
            "ground_truth": ground_truth,
        }
    )

    peer_medians = df_features.groupby(["area_zone", "category"])["latest_kwh"].transform("median")
    df_features["peer_ratio"] = np.round(
        df_features["latest_kwh"] / (peer_medians + 1e-5),
        4,
    )
    df_features["risk_score"] = 0
    df_features["status"] = "Normal"

    records = df_features.to_dict(orient="records")
    for rec in records:
        rec["shap_values"] = {}

    print(
        f"Prepared {len(records):,} consumer docs with 8 behavioral features "
        f"({n_tampered:,} synthetic theft cases, {n_tampered / n_rows * 100:.2f}%)."
    )
    return records


def main() -> None:
    if not ping_db():
        raise RuntimeError("MongoDB ping failed.")
    print("MongoDB connection verified.")

    raw_csv_path = locate_raw_csv()
    print(f"Located raw dataset: {raw_csv_path}")

    raw_df = pd.read_csv(raw_csv_path)
    print(f"Raw shape: {raw_df.shape[0]:,} rows x {raw_df.shape[1]} columns")

    consumption_col = detect_consumption_column(raw_df)
    print(f"Selected baseline consumption column for avg_6m: '{consumption_col}'")

    cleaned_df = clean_raw_dataset(raw_df, consumption_col)
    docs = build_consumer_documents(cleaned_df, consumption_col)

    inserted = seed_consumers(docs, clear_existing=True, batch_size=5000)
    print(f"Seeded {inserted:,} consumer documents into MongoDB (electricity_theft_db.consumers).")


if __name__ == "__main__":
    main()
