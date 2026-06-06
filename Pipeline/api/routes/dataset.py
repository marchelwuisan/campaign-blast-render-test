from fastapi import APIRouter, UploadFile, File, HTTPException
import csv
import io
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from Pipeline.config import DATA_PATH
from Pipeline.data.loader import load_customers
from Pipeline.engine.analyzer import analyze
from Pipeline.database.db import transaction

REQUIRED_COLUMNS = {
    "customer_id", "phone_number", "created_at",
    "purchase_date", "order_value", "product_category",
}

_META_PATH = Path(DATA_PATH).parent / "dataset_meta.json"

router = APIRouter()


def _read_meta() -> dict:
    try:
        with open(_META_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_meta(meta: dict):
    with open(_META_PATH, "w") as f:
        json.dump(meta, f)


@router.get("/status")
def get_dataset_status():
    exists = os.path.exists(DATA_PATH)
    meta = _read_meta()

    if not exists and not meta:
        return {"status": "no_dataset"}

    result: dict = {
        "status": "ready" if exists else "no_dataset",
        "last_uploaded": meta.get("uploaded_at"),
        "original_filename": meta.get("original_filename"),
        "row_count": meta.get("row_count"),
        "last_analyzed_at": meta.get("analyzed_at"),
        "ml_enabled": meta.get("ml_enabled"),
        "analyzed_customer_count": meta.get("analyzed_customer_count"),
    }

    if exists and not meta.get("uploaded_at"):
        mtime = os.path.getmtime(DATA_PATH)
        result["last_uploaded"] = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()

    return result


@router.post("/upload")
async def upload_dataset(file: UploadFile = File(...)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are accepted.")

    content = await file.read()

    try:
        decoded = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded.")

    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV is empty.")

    missing = REQUIRED_COLUMNS - {c.strip().lower() for c in reader.fieldnames}
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required columns: {sorted(missing)}",
        )

    row_count = sum(1 for _ in reader)

    data_path = Path(DATA_PATH)
    tmp_path = data_path.with_suffix(".tmp")
    tmp_path.write_bytes(content)
    shutil.move(str(tmp_path), str(data_path))

    with transaction() as conn:
        conn.execute("DELETE FROM analyzed_customers")

    if _META_PATH.exists():
        _META_PATH.unlink()

    uploaded_at = datetime.now(tz=timezone.utc).isoformat()
    _write_meta({
        "uploaded_at": uploaded_at,
        "original_filename": file.filename,
        "row_count": row_count,
    })

    return {
        "status": "uploaded",
        "filename": file.filename,
        "row_count": row_count,
        "uploaded_at": uploaded_at,
    }


@router.post("/analyze")
def analyze_dataset(ml_enabled: bool = False):
    if not os.path.exists(DATA_PATH):
        raise HTTPException(
            status_code=404,
            detail="No dataset found. Upload a transactions.csv first.",
        )

    customers, date_cutoff = load_customers(DATA_PATH)
    at_risk, _, _ = analyze(customers, date_cutoff, ml_enabled=ml_enabled)

    analyzed_at = datetime.now(tz=timezone.utc).isoformat()

    with transaction() as conn:
        conn.execute("DELETE FROM analyzed_customers")
        conn.executemany(
            """
            INSERT INTO analyzed_customers (
                customer_id, name, phone, gender, age, risk_level,
                rfm_r_score, rfm_f_score, rfm_m_score, rfm_combined_score,
                days_since_last_purchase, total_spend, avg_order_value,
                top_category, triggered_rules, churn_probability,
                ml_enabled, analyzed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    c.customer_id, c.name, c.phone, c.gender, c.age, c.risk_level,
                    c.rfm.r_score, c.rfm.f_score, c.rfm.m_score, c.rfm.combined_score,
                    c.days_since_last_purchase,
                    c.spend_summary.total_spend, c.spend_summary.avg_order_value,
                    c.spend_summary.top_category,
                    json.dumps(c.triggered_rules),
                    c.churn_probability,
                    int(ml_enabled),
                    analyzed_at,
                )
                for c in at_risk
            ],
        )

    meta = _read_meta()
    meta.update({
        "analyzed_at": analyzed_at,
        "ml_enabled": ml_enabled,
        "analyzed_customer_count": len(at_risk),
    })
    _write_meta(meta)

    return {
        "status": "analyzed",
        "at_risk_count": len(at_risk),
        "ml_enabled": ml_enabled,
        "analyzed_at": analyzed_at,
    }
