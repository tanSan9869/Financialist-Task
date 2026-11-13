import gspread
from .google_auth import get_credentials


def read_applicants(cfg):
    gc = gspread.authorize(get_credentials())
    sh = gc.open_by_key(cfg["sheet"]["id"])
    ws = sh.worksheet(cfg["sheet"]["worksheet"]) if cfg["sheet"].get("worksheet") else sh.sheet1
    cols = cfg["sheet"]["columns"]
    rows = []
    for i, rec in enumerate(ws.get_all_records(), start=2):
        rows.append({
            "row_number": i,
            "name": str(rec.get(cols["name"], "")).strip(),
            "email": str(rec.get(cols["email"], "")).strip(),
            "role": str(rec.get(cols["role"], "")).strip(),
            "cv_link": str(rec.get(cols["cv_link"], "")).strip(),
        })
    return [r for r in rows if any([r["name"], r["email"], r["cv_link"]])]
