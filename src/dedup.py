import hashlib
import re
import requests
from .coda_writer import headers, url


def norm_email(e):
    e = (e or "").strip().lower()
    m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", e)  # strips markdown/mailto wrappers Coda may return
    return m.group(0) if m else e


def applicant_id(email, fallback=""):
    return hashlib.sha256((norm_email(email) or fallback).encode()).hexdigest()[:12]


class Existing:
    """Snapshot of what is already in the Coda table (ids, emails, CV hashes)."""

    def __init__(self, cfg):
        names = cfg["coda"]["columns"]
        self.ids, self.emails, self.hashes = set(), set(), set()
        params = {"useColumnNames": "true", "limit": 200}
        next_url = url(cfg, "rows")
        while next_url:
            r = requests.get(next_url, headers=headers(), params=params, timeout=60)
            r.raise_for_status()
            d = r.json()
            for row in d["items"]:
                v = row["values"]
                # rows that failed only because scoring/API broke are retried, not treated as done
                if (str(v.get(names["status"], "")) == "Failed"
                        and str(v.get(names["error_note"], "")).startswith("Scoring failed")):
                    continue
                if v.get(names["applicant_id"]):
                    self.ids.add(str(v[names["applicant_id"]]).strip())
                if v.get(names["email"]):
                    self.emails.add(norm_email(str(v[names["email"]])))
                if v.get(names.get("cv_hash", "")):
                    self.hashes.add(str(v[names["cv_hash"]]).strip())
            next_url, params = d.get("nextPageLink"), None

    def seen_applicant(self, aid, email):
        return aid in self.ids or norm_email(email) in self.emails

    def seen_hash(self, h):
        return bool(h) and h in self.hashes

    def add(self, aid, email, h):
        self.ids.add(aid)
        self.emails.add(norm_email(email))
        if h:
            self.hashes.add(h)
