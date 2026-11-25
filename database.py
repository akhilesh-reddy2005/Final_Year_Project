"""MongoDB database connection, indexing, and CRUD helpers for electricity theft detection."""

from __future__ import annotations

from datetime import datetime, timezone
import os
import re
from typing import Any
from dotenv import load_dotenv
import pandas as pd
from pymongo import ASCENDING, DESCENDING, MongoClient, UpdateOne
from pymongo.database import Database


load_dotenv(override=True)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = "electricity_theft_db"

_CLIENT: MongoClient | None = None
_INDEXES_READY = False


def get_client() -> MongoClient:
    """Return a cached MongoClient connected to the configured MONGO_URI."""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=15000,
            connectTimeoutMS=15000,
        )
    return _CLIENT


def get_db() -> Database:
    """Return the electricity_theft_db database handle."""
    return get_client()[DB_NAME]


def ping_db() -> bool:
    """Verify connectivity to MongoDB with an admin ping command."""
    res = get_client().admin.command("ping")
    return bool(res.get("ok") == 1)


def ensure_indexes() -> None:
    """Create required indexes on consumers, meter_readings, and inspections collections."""
    global _INDEXES_READY
    if _INDEXES_READY:
        return
    db = get_db()
    db.consumers.create_index([("consumer_id", ASCENDING)], unique=True)
    db.consumers.create_index(
        [("area_zone", ASCENDING), ("status", ASCENDING), ("risk_score", DESCENDING)]
    )
    db.meter_readings.create_index([("consumer_id", ASCENDING), ("reading_date", DESCENDING)])
    db.inspections.create_index([("consumer_id", ASCENDING), ("inspected_at", DESCENDING)])
    _INDEXES_READY = True


def seed_consumers(
    docs: list[dict[str, Any]],
    clear_existing: bool = True,
    batch_size: int = 5000,
) -> int:
    """Seed consumer documents into MongoDB in batches."""
    ensure_indexes()
    col = get_db().consumers
    if clear_existing:
        col.delete_many({})

    inserted = 0
    for start in range(0, len(docs), batch_size):
        batch = docs[start : start + batch_size]
        col.insert_many(batch, ordered=False)
        inserted += len(batch)
    return inserted


def load_consumers_dataframe(projection: dict[str, int] | None = None) -> pd.DataFrame:
    """Load consumer documents from MongoDB into a Pandas DataFrame (excluding _id)."""
    ensure_indexes()
    proj = {"_id": 0} if projection is None else {**projection, "_id": 0}
    docs = list(get_db().consumers.find({}, proj))
    return pd.DataFrame(docs)


def bulk_update_consumer_scores(
    updates: list[dict[str, Any]],
    batch_size: int = 5000,
) -> int:
    """Bulk-update risk_score, status, and shap_values on consumer documents."""
    ensure_indexes()
    col = get_db().consumers
    modified = 0
    for start in range(0, len(updates), batch_size):
        batch = updates[start : start + batch_size]
        ops = [
            UpdateOne(
                {"consumer_id": item["consumer_id"]},
                {
                    "$set": {
                        "risk_score": int(item["risk_score"]),
                        "status": str(item["status"]),
                        "shap_values": item["shap_values"],
                    }
                },
            )
            for item in batch
        ]
        if ops:
            result = col.bulk_write(ops, ordered=False)
            modified += result.matched_count
    return modified


def query_consumers(
    zone: str = "All",
    category: str = "All",
    status: str = "Flagged",
    limit: int = 500,
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    """Query filtered/ranked consumers and compute scoped KPIs from MongoDB."""
    ensure_indexes()
    db = get_db()
    col = db.consumers
    scope_filter: dict[str, Any] = {}
    if zone != "All":
        scope_filter["area_zone"] = zone
    if category != "All":
        scope_filter["category"] = category

    consumers_monitored = int(col.count_documents(scope_filter))
    cases_flagged = int(col.count_documents({**scope_filter, "risk_score": {"$gte": 40}}))
    high_risk = int(col.count_documents({**scope_filter, "risk_score": {"$gte": 70}}))
    verified_detections = int(db.inspections.count_documents({"outcome": "Confirmed Theft"}))
    total_inspections = int(db.inspections.count_documents({}))

    kpis = {
        "consumers_monitored": consumers_monitored,
        "cases_flagged": cases_flagged,
        "high_risk": high_risk,
        "verified_detections": verified_detections,
        "total_inspections": total_inspections,
        "flagged_pct": (cases_flagged / consumers_monitored * 100.0) if consumers_monitored else 0.0,
        "high_risk_pct": (high_risk / consumers_monitored * 100.0) if consumers_monitored else 0.0,
    }

    if status == "Flagged":
        query_filter = {**scope_filter, "status": {"$in": ["Inspect", "Watchlist"]}}
    elif status in ("Inspect", "Watchlist", "Normal"):
        query_filter = {**scope_filter, "status": status}
    else:
        query_filter = scope_filter

    total_matching = int(col.count_documents(query_filter))
    rows = list(
        col.find(query_filter, {"_id": 0})
        .sort([("risk_score", DESCENDING), ("pct_change_from_avg", ASCENDING)])
        .limit(limit)
    )
    return rows, total_matching, kpis


def get_zone_tariff_analytics() -> dict[str, Any]:
    """Aggregate consumer counts, flagged rates, and average scores by zone and category."""
    ensure_indexes()
    pipeline = [
        {
            "$group": {
                "_id": {"area_zone": "$area_zone", "category": "$category"},
                "total": {"$sum": 1},
                "flagged": {"$sum": {"$cond": [{"$gte": ["$risk_score", 40]}, 1, 0]}},
                "inspect": {"$sum": {"$cond": [{"$gte": ["$risk_score", 70]}, 1, 0]}},
                "watchlist": {
                    "$sum": {
                        "$cond": [
                            {"$and": [{"$gte": ["$risk_score", 40]}, {"$lt": ["$risk_score", 70]}]},
                            1,
                            0,
                        ]
                    }
                },
                "avg_risk": {"$avg": "$risk_score"},
                "avg_kwh": {"$avg": "$latest_kwh"},
            }
        }
    ]
    raw_groups = list(get_db().consumers.aggregate(pipeline))

    zone_map: dict[str, dict[str, Any]] = {}
    cat_map: dict[str, dict[str, Any]] = {}
    breakdown: list[dict[str, Any]] = []

    for g in raw_groups:
        zone = str(g["_id"]["area_zone"])
        cat = str(g["_id"]["category"])
        total = int(g["total"])
        flagged = int(g["flagged"])
        inspect = int(g["inspect"])
        watchlist = int(g["watchlist"])
        avg_risk = float(g["avg_risk"] or 0.0)
        avg_kwh = float(g["avg_kwh"] or 0.0)

        breakdown.append(
            {
                "area_zone": zone,
                "category": cat,
                "total": total,
                "flagged": flagged,
                "inspect": inspect,
                "watchlist": watchlist,
                "flagged_pct": round((flagged / total * 100.0) if total else 0.0, 2),
                "avg_risk": round(avg_risk, 2),
                "avg_kwh": round(avg_kwh, 1),
            }
        )

        for bucket, key in ((zone_map, zone), (cat_map, cat)):
            entry = bucket.setdefault(
                key,
                {"name": key, "total": 0, "flagged": 0, "inspect": 0, "watchlist": 0, "risk_sum": 0.0, "kwh_sum": 0.0},
            )
            entry["total"] += total
            entry["flagged"] += flagged
            entry["inspect"] += inspect
            entry["watchlist"] += watchlist
            entry["risk_sum"] += avg_risk * total
            entry["kwh_sum"] += avg_kwh * total

    def finalize(bucket: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for entry in bucket.values():
            t = entry["total"]
            out.append(
                {
                    "name": entry["name"],
                    "total": t,
                    "flagged": entry["flagged"],
                    "inspect": entry["inspect"],
                    "watchlist": entry["watchlist"],
                    "flagged_pct": round((entry["flagged"] / t * 100.0) if t else 0.0, 2),
                    "avg_risk": round((entry["risk_sum"] / t) if t else 0.0, 2),
                    "avg_kwh": round((entry["kwh_sum"] / t) if t else 0.0, 1),
                }
            )
        return sorted(out, key=lambda x: x["name"])

    return {
        "by_zone": finalize(zone_map),
        "by_category": finalize(cat_map),
        "breakdown": sorted(breakdown, key=lambda x: (x["area_zone"], x["category"])),
    }


def get_consumer_by_id(consumer_id: str) -> dict[str, Any] | None:
    """Fetch a single consumer document by consumer_id (excluding _id)."""
    ensure_indexes()
    doc = get_db().consumers.find_one(
        {"consumer_id": consumer_id.strip().upper()},
        {"_id": 0},
    )
    return doc


def search_consumer_ids(query: str = "", limit: int = 50) -> list[str]:
    """Search consumer IDs matching a query substring, or return top-risk seed IDs."""
    ensure_indexes()
    col = get_db().consumers
    cleaned = query.strip().upper()
    if not cleaned:
        cursor = col.find({}, {"_id": 0, "consumer_id": 1}).sort("risk_score", DESCENDING).limit(limit)
    else:
        pattern = re.escape(cleaned)
        cursor = col.find(
            {"consumer_id": {"$regex": pattern, "$options": "i"}},
            {"_id": 0, "consumer_id": 1},
        ).limit(limit)
    return [doc["consumer_id"] for doc in cursor]


def get_distinct_zones_and_categories() -> tuple[list[str], list[str]]:
    """Return sorted distinct area_zone and category values from MongoDB."""
    ensure_indexes()
    col = get_db().consumers
    zones = sorted(str(z) for z in col.distinct("area_zone") if z)
    categories = sorted(str(c) for c in col.distinct("category") if c)
    return zones, categories


def get_peer_medians() -> dict[tuple[str, str], tuple[float, float]]:
    """Compute median latest_kwh and std_dev grouped by (area_zone, category)."""
    ensure_indexes()
    docs = list(
        get_db().consumers.find(
            {},
            {"_id": 0, "area_zone": 1, "category": 1, "latest_kwh": 1, "std_dev": 1},
        )
    )
    if not docs:
        return {}
    df = pd.DataFrame(docs)
    grouped = (
        df.groupby(["area_zone", "category"])
        .agg(
            peer_median_kwh=("latest_kwh", "median"),
            peer_median_std=("std_dev", "median"),
        )
        .reset_index()
    )
    return {
        (str(row["area_zone"]), str(row["category"])): (
            float(row["peer_median_kwh"]),
            float(row["peer_median_std"]),
        )
        for _, row in grouped.iterrows()
    }


def get_next_consumer_id() -> str:
    """Compute the next sequential KA-xxxxx ID not present in consumers."""
    ensure_indexes()
    col = get_db().consumers
    docs = col.find(
        {"consumer_id": {"$regex": r"^KA-\d+$"}},
        {"_id": 0, "consumer_id": 1},
    )
    max_num = 9999
    existing = set()
    for doc in docs:
        cid = str(doc["consumer_id"])
        existing.add(cid.upper())
        try:
            num = int(cid.split("-", 1)[1])
            if num > max_num:
                max_num = num
        except (IndexError, ValueError):
            continue

    next_num = max_num + 1
    candidate = f"KA-{next_num}"
    while candidate.upper() in existing:
        next_num += 1
        candidate = f"KA-{next_num}"
    return candidate


def insert_consumer(doc: dict[str, Any]) -> dict[str, Any]:
    """Insert a new consumer document into MongoDB and return a JSON-safe copy."""
    ensure_indexes()
    clean_doc = dict(doc)
    get_db().consumers.insert_one(clean_doc)
    clean_doc.pop("_id", None)
    return clean_doc


def update_consumer_reading(consumer_id: str, update_fields: dict[str, Any]) -> None:
    """Update consumption metrics, risk score, status, and SHAP values for a consumer."""
    ensure_indexes()
    get_db().consumers.update_one(
        {"consumer_id": consumer_id.strip().upper()},
        {"$set": update_fields},
    )


def log_meter_reading(
    consumer_id: str,
    units_kwh: float,
    risk_score: int,
    status: str,
) -> dict[str, Any]:
    """Insert a historical reading entry into meter_readings."""
    ensure_indexes()
    now_iso = datetime.now(timezone.utc).isoformat()
    doc = {
        "consumer_id": consumer_id.strip().upper(),
        "reading_date": now_iso,
        "units_kwh": float(units_kwh),
        "risk_score": int(risk_score),
        "status": str(status),
    }
    res = get_db().meter_readings.insert_one(doc)
    doc["_id"] = str(res.inserted_id)
    return doc


def record_inspection(
    consumer_id: str,
    outcome: str,
    ground_truth: int,
    remarks: str = "",
) -> dict[str, Any]:
    """Record a field vigilance inspection outcome and update consumer ground_truth."""
    ensure_indexes()
    cid = consumer_id.strip().upper()
    now_iso = datetime.now(timezone.utc).isoformat()
    db = get_db()

    inspection_doc = {
        "consumer_id": cid,
        "inspected_at": now_iso,
        "outcome": str(outcome),
        "remarks": str(remarks),
    }
    res = db.inspections.insert_one(inspection_doc)
    db.consumers.update_one(
        {"consumer_id": cid},
        {"$set": {"ground_truth": int(ground_truth)}},
    )
    inspection_doc["_id"] = str(res.inserted_id)
    return inspection_doc


def get_latest_inspection(consumer_id: str) -> dict[str, Any] | None:
    """Return the most recent inspection log for a consumer, if any."""
    ensure_indexes()
    doc = get_db().inspections.find_one(
        {"consumer_id": consumer_id.strip().upper()},
        sort=[("inspected_at", DESCENDING)],
    )
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc
