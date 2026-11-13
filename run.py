"""Daily run: Google Sheet -> dedup -> extract -> score (Groq) -> upsert into Coda."""
import json
import os
import sys
import time
from datetime import datetime, timezone

from src.coda_writer import make_record, table_columns, write_row
from src.config import load_config
from src.dedup import Existing, applicant_id, norm_email
from src.extractor import extract
from src.scorer import score
from src.sheet_reader import read_applicants


def resolve_role(cfg, name):
    n = name.strip().lower()
    for key, r in cfg["roles"].items():
        if n == key.lower() or n in [a.lower() for a in r.get("aliases", [])]:
            return key
    return None


def main():
    cfg = load_config()
    os.makedirs("logs", exist_ok=True)
    log_path = f"logs/run_{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"

    def log(aid, status, error=""):
        entry = {"timestamp": datetime.now(timezone.utc).isoformat(), "applicant_id": aid,
                 "status": status, "error": error}
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        print(f"[{status}] {aid} {error}")

    applicants = read_applicants(cfg)
    cols = table_columns(cfg)
    existing = Existing(cfg)
    print(f"{len(applicants)} sheet rows, {len(existing.ids)} already in Coda")
    counts = {"Scored": 0, "Failed": 0, "Skipped": 0}

    for app in applicants:
        aid = applicant_id(app["email"], app["cv_link"])
        try:
            if existing.seen_applicant(aid, app["email"]):
                counts["Skipped"] += 1
                log(aid, "Skipped", "already in Coda")
                continue

            cv_hash, result, error = None, None, ""
            if not app["email"] or "@" not in app["email"]:
                error = "Missing or invalid email"
            elif not resolve_role(cfg, app["role"]):
                error = f"Unknown role '{app['role']}' (not in config.yaml roles)"
            else:
                ex = extract(app["cv_link"], cfg.get("min_cv_chars", 80))
                cv_hash = ex.cv_hash
                if ex.retryable:  # environment problem: don't write a Failed row, retry next run
                    counts["Skipped"] += 1
                    log(aid, "Deferred", ex.error)
                    continue
                if not ex.ok:
                    error = ex.error
                elif existing.seen_hash(cv_hash):
                    counts["Skipped"] += 1
                    log(aid, "Skipped", "duplicate CV content (same hash)")
                    continue
                else:
                    result, error = score(cfg, resolve_role(cfg, app["role"]), ex.text)

            write_row(cfg, cols, make_record(app, aid, cv_hash, result, error))
            existing.add(aid, app["email"], cv_hash)
            status = "Scored" if result else "Failed"
            counts[status] += 1
            log(aid, status, error)
            time.sleep(0.5)  # gentle on Groq / Coda rate limits
        except Exception as e:  # one bad row never aborts the batch
            counts["Failed"] += 1
            log(aid, "Failed", f"Unexpected: {type(e).__name__}: {e}"[:300])
            try:
                write_row(cfg, cols, make_record(app, aid, None, None, f"Unexpected: {e}"[:300]))
                existing.add(aid, app["email"], None)
            except Exception as e2:
                log(aid, "WriteFailed", str(e2)[:300])

    print("Done:", counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
