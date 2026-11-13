import os
import re
import yaml
from dotenv import load_dotenv

load_dotenv()


def load_config(path="config.yaml"):
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["coda"]["doc_id"] = os.getenv("CODA_DOC_ID") or cfg["coda"]["doc_id"]
    cfg["coda"]["table_id"] = os.getenv("CODA_TABLE_ID") or cfg["coda"]["table_id"]
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not sheet_id:
        m = re.search(r"/d/([\w-]+)", cfg["sheet"]["url"] or "")
        sheet_id = m.group(1) if m else None
    cfg["sheet"]["id"] = sheet_id
    return cfg
