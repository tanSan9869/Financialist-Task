import json
import os
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def get_credentials():
    """Service account from GOOGLE_SERVICE_ACCOUNT_JSON (CI) or GOOGLE_SERVICE_ACCOUNT_FILE (local)."""
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        return Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "applicant-scoring-pipeline.json")
    return Credentials.from_service_account_file(path, scopes=SCOPES)
