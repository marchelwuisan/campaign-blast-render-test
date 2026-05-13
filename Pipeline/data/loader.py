import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from Pipeline.data.schema import Customer, Transaction
from Pipeline.config import MIN_CUSTOMER_AGE_DAYS, WA_REGISTRATION_CHECK, LOG_DIR

REQUIRED_COLUMNS = {
    "customer_id", "phone_number", "created_at",
    "purchase_date", "order_value", "product_category",
}

# Matches Indonesian mobile numbers in various formats → normalizes to E.164 (+62...)
_PHONE_RE = re.compile(r"^(?:\+?62|0)(\d{8,12})$")


def _normalize_phone(raw: str) -> str | None:
    cleaned = re.sub(r"[\s\-().]+", "", raw.strip())
    m = _PHONE_RE.match(cleaned)
    if not m:
        return None
    return f"+62{m.group(1)}"


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def load_customers(csv_path: str) -> tuple[List[Customer], datetime]:
    path = Path(csv_path)
    if not path.exists():
        print(f"[loader] ERROR: file not found: {csv_path}")
        sys.exit(1)

    log_dir = Path(LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    skipped_log = log_dir / "skipped.jsonl"
    failed_transactions_log = log_dir / "failed_transactions.jsonl"

    skipped: list[dict] = []
    failed_transactions: list[dict] = []

    raw_rows: list[dict] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = set(reader.fieldnames or [])

        missing = REQUIRED_COLUMNS - headers
        if missing:
            print(f"[loader] ERROR: missing required columns: {sorted(missing)}")
            sys.exit(1)

        seen_txns: set[tuple] = set()
        duplicates: list[dict] = []
        
        for i, row in enumerate(reader, start=2):  # row 1 = header
            key = (row["customer_id"], row["purchase_date"], row["order_value"])
            # Check for duplicates based on (customer_id, purchase_date, order_value)
            if key not in seen_txns:
                seen_txns.add(key)
                raw_rows.append({"_row": i, **row})
            else:
                duplicates.append({"_row": i, **row})

    # Derive cutoff from the dataset's own max purchase_date — makes pipeline dataset-relative
    parsed_dates = [
        datetime.strptime(row["purchase_date"].strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        for row in raw_rows if row.get("purchase_date", "").strip()
    ]
    date_cutoff = max(parsed_dates) if parsed_dates else datetime.now(tz=timezone.utc)

    # Build per-customer transaction lists
    customer_rows: dict[str, list[dict]] = {}
    for row in raw_rows:
        cid = row["customer_id"].strip()
        customer_rows.setdefault(cid, []).append(row)

    customers: list[Customer] = []

    # customer_rows: { "CUST001": [{"_row": 2, "customer_id": "CUST001", "purchase_date": "...", "order_value": "...", ...}] }
    for cid, rows in customer_rows.items():
        first = rows[0]
        row_num = first["_row"]

        # --- phone ---
        phone = _normalize_phone(first.get("phone_number", ""))
        if phone is None:
            skipped.append({"customer_id": cid, "reason": "invalid_phone", "raw": first.get("phone_number")})
            continue

        # --- created_at ---
        created_at = _parse_date(first.get("created_at", ""))
        if created_at is None:
            skipped.append({"customer_id": cid, "reason": "invalid_created_at", "raw": first.get("created_at")})
            continue

        # --- too new to score ---
        age_days = (date_cutoff - created_at).days
        if age_days < MIN_CUSTOMER_AGE_DAYS:
            skipped.append({"customer_id": cid, "reason": "customer_too_new", "age_days": age_days})
            continue

        # --- transactions ---
        transactions: list[Transaction] = []
        for row in rows:
            purchase_date = _parse_date(row.get("purchase_date", ""))
            if purchase_date is None:
                failed_transactions.append({"customer_id": cid, "row": row["_row"], "reason": "invalid_purchase_date", "raw": row.get("purchase_date")})
                continue
            try:
                quantity = int(row.get("quantity", 1))
                price_per_unit = float(row.get("price_per_unit", 0))
                order_value = float(row["order_value"]) if row.get("order_value") else quantity * price_per_unit
            except (ValueError, TypeError):
                failed_transactions.append({"customer_id": cid, "row": row["_row"], "reason": "invalid_numeric_fields", "raw": {"order_value": row.get("order_value"), "quantity": row.get("quantity"), "price_per_unit": row.get("price_per_unit")}})
                continue

            transactions.append(Transaction(
                transaction_id=row.get("transaction_id", "").strip(),
                purchase_date=purchase_date,
                order_value=order_value,
                product_category=row.get("product_category", "").strip(),
                quantity=quantity,
                price_per_unit=price_per_unit,
            ))

        if not transactions:
            skipped.append({"customer_id": cid, "reason": "no_valid_transactions"})
            continue

        customer_name = first.get("customer_name", "").strip() or f"Customer {cid}"
        gender = first.get("gender", "").strip() or None
        age_raw = first.get("age", "")
        try:
            age = int(age_raw) if age_raw else None
        except ValueError:
            age = None

        customers.append(Customer(
            customer_id=cid,
            customer_name=customer_name,
            phone_number=phone,
            created_at=created_at,
            gender=gender,
            age=age,
            transactions=transactions,
        ))

    # Write skipped log
    with open(skipped_log, "w", encoding="utf-8") as f:
        for entry in skipped:
            f.write(json.dumps(entry) + "\n")

    with open(failed_transactions_log, "w", encoding="utf-8") as f:
        for entry in failed_transactions:
            f.write(json.dumps(entry) + "\n")

    print(f"[loader] loaded {len(customers)} customers ({len(skipped)} skipped) from {path.name}")
    return customers, date_cutoff
