import json
from datetime import datetime, timezone

from Pipeline.database.db import transaction


def _to_row(template: dict) -> tuple:
    return (
        template.get("id"),
        template.get("name"),
        template.get("status"),
        template.get("language"),
        template.get("category"),
        json.dumps(template),
        datetime.now(timezone.utc).isoformat(),
    )


def replace_all(templates: list[dict]) -> int:
    rows = [_to_row(t) for t in templates if t.get("id")]
    with transaction() as conn:
        conn.execute("DELETE FROM templates")
        conn.executemany(
            """
            INSERT INTO templates (id, name, status, language, category, raw, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


def list_local(
    name: str | None = None,
    status: str | None = None,
    language: str | None = None,
    limit: int = 25,
) -> list[dict]:
    filters, params = [], []
    if name:
        filters.append("name = ?")
        params.append(name)
    if status:
        filters.append("status = ?")
        params.append(status)
    if language:
        filters.append("language = ?")
        params.append(language)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    params.append(limit)

    with transaction() as conn:
        rows = conn.execute(
            f"SELECT raw FROM templates {where} ORDER BY name LIMIT ?",
            params,
        ).fetchall()
    return [json.loads(r["raw"]) for r in rows]


def get_local(template_id: str) -> dict | None:
    with transaction() as conn:
        row = conn.execute(
            "SELECT raw FROM templates WHERE id = ?", (template_id,)
        ).fetchone()
    return json.loads(row["raw"]) if row else None


def count_local() -> int:
    with transaction() as conn:
        return conn.execute("SELECT COUNT(*) FROM templates").fetchone()[0]
