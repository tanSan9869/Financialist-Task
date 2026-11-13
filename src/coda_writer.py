import json
import os
import requests
from datetime import datetime, timezone

BASE = "https://coda.io/apis/v1"


def headers():
    return {"Authorization": f"Bearer {os.environ['CODA_API_TOKEN']}", "Content-Type": "application/json"}


def url(cfg, tail):
    return f"{BASE}/docs/{cfg['coda']['doc_id']}/tables/{cfg['coda']['table_id']}/{tail}"


def table_columns(cfg):
    r = requests.get(url(cfg, "columns"), headers=headers(), timeout=30)
    r.raise_for_status()
    return {c["name"] for c in r.json()["items"]}


def write_row(cfg, available_cols, rec):
    """Upsert one row keyed on Applicant ID. Columns missing from the table are skipped."""
    names = cfg["coda"]["columns"]
    cells = []
    for k, v in rec.items():
        col = names.get(k)
        if col and col in available_cols and v is not None:
            cells.append({"column": col, "value": v})
    payload = {"rows": [{"cells": cells}], "keyColumns": [names["applicant_id"]]}
    r = requests.post(url(cfg, "rows"), headers=headers(), json=payload, timeout=30)
    if r.status_code not in (200, 202):
        raise RuntimeError(f"Coda write failed {r.status_code}: {r.text[:300]}")


def make_record(app, applicant_id, cv_hash, result=None, error=""):
    rec = {"applicant_id": applicant_id, "name": app["name"], "email": app["email"], "role": app["role"],
           "cv_link": app["cv_link"], "date": datetime.now(timezone.utc).isoformat(),
           "cv_hash": cv_hash, "error_note": error}
    if result:
        rec.update(total_score=result["total_score"], sub_scores=json.dumps(result["sub_scores"]),
                   recommendation=result["recommendation"], reason=result["reason"], status="Scored")
    else:
        rec["status"] = "Failed"
    return rec
