"""
Transform datasets/online_retail/online_retail.csv
into the Pipeline-compatible CSV schema:

  customer_id, phone_number, created_at,
  purchase_date, order_value, product_category,
  transaction_id, quantity, price_per_unit

Stubs for unavailable fields:
  - phone_number  → +62812<8-digit CustomerID zero-padded>
  - created_at    → earliest InvoiceDate for that customer
  - product_category → Description (first 50 chars, title-cased)
"""

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path

SRC = Path("online_retail.csv")
DST = Path("transactions.csv")

_DATE_FMTS = ["%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]


def _parse_invoice_date(raw: str) -> datetime | None:
    for fmt in _DATE_FMTS:
        try:
            return datetime.strptime(raw.strip(), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _stub_phone(customer_id: str) -> str:
    digits = "".join(filter(str.isdigit, customer_id))
    padded = digits.zfill(8)[-8:]
    return f"+628120{padded}"


def main() -> None:
    # Pass 1: collect earliest InvoiceDate per CustomerID (for created_at stub)
    earliest: dict[str, datetime] = {}
    with open(SRC, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cid = row["CustomerID"].strip()
            if not cid or cid == "nan":
                continue
            dt = _parse_invoice_date(row["InvoiceDate"])
            if dt and (cid not in earliest or dt < earliest[cid]):
                earliest[cid] = dt

    # Pass 2: write transformed rows
    out_fields = [
        "customer_id", "phone_number", "created_at",
        "purchase_date", "order_value", "product_category",
        "transaction_id", "quantity", "price_per_unit",
    ]

    written = skipped = 0
    with open(SRC, newline="", encoding="utf-8") as fin, \
         open(DST, "w", newline="", encoding="utf-8") as fout:

        writer = csv.DictWriter(fout, fieldnames=out_fields)
        writer.writeheader()

        for row in csv.DictReader(fin):
            cid = row["CustomerID"].strip()
            if not cid or cid == "nan":
                skipped += 1
                continue

            purchase_dt = _parse_invoice_date(row["InvoiceDate"])
            if purchase_dt is None:
                skipped += 1
                continue

            try:
                quantity = int(row["Quantity"])
                price_per_unit = float(row["UnitPrice"])
            except (ValueError, TypeError):
                skipped += 1
                continue

            if quantity <= 0 or price_per_unit < 0:
                skipped += 1
                continue

            order_value = round(quantity * price_per_unit, 2)

            invoice_no = row["InvoiceNo"].strip()
            stock_code = row["StockCode"].strip()
            txn_id = f"{invoice_no}-{stock_code}"

            category = row["Description"].strip().title()[:50]

            created_dt = earliest.get(cid, purchase_dt)

            writer.writerow({
                "customer_id":      cid,
                "phone_number":     _stub_phone(cid),
                "created_at":       created_dt.strftime("%Y-%m-%d"),
                "purchase_date":    purchase_dt.strftime("%Y-%m-%d"),
                "order_value":      order_value,
                "product_category": category,
                "transaction_id":   txn_id,
                "quantity":         quantity,
                "price_per_unit":   price_per_unit,
            })
            written += 1

    print(f"[transform] wrote {written} rows → {DST}  ({skipped} skipped)")


if __name__ == "__main__":
    main()
