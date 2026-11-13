# Daily Applicant Scoring Pipeline

Reads new applicants from a Google Sheet, scores each CV with an LLM (Groq) against a per-role rubric, and upserts one row per applicant into a Coda table. Runs daily via GitHub Actions.

```
GitHub Actions cron -> run.py -> Google Sheet (name,email,role,CV link)
   -> dedup (Coda: Applicant ID / email / CV hash) -> extractor (pdf/docx/doc/txt/image/OCR/gdoc)
   -> scorer (Groq, strict JSON) -> coda_writer (upsert on Applicant ID) -> logs/run_YYYY-MM-DD.jsonl
```

## Setup
1. `pip install -r requirements.txt` (OCR locally also needs the Tesseract and Poppler binaries; CI installs them).
2. Copy secrets into `.env` (git-ignored): `GROQ_API_KEY`, `CODA_API_TOKEN`, `CODA_DOC_ID`, `CODA_TABLE_ID`, `GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_FILE`.
3. Share the Google Sheet **and** the Drive CV folder with the service-account email (Viewer), or set CV files to "anyone with link".
4. Coda table columns: Applicant ID, Name, Email, Role, CV Link, Total Score, Sub-scores, Recommendation, Reason, Date, Status, Error Note. Optional: add a text column `CV Hash` to enable CV-content dedup.
5. `python run.py`
6. CI: add the same values as GitHub repo secrets (`GOOGLE_SERVICE_ACCOUNT_JSON` = full JSON contents). Workflow: `.github/workflows/daily_run.yml` (daily 07:00 UTC + manual `workflow_dispatch`).

## Daily run
For each sheet row: skip if the Applicant ID (`sha256(email)[:12]`) or email is already in Coda, or the CV hash was seen; otherwise extract text, score, write. Failures (corrupt/empty file, OCR failure, unknown role, API error) are written with `Status=Failed` and an `Error Note`; the batch continues. Writes use `keyColumns: ["Applicant ID"]`, so they upsert and never duplicate. Failed rows are not retried automatically: delete the row in Coda to retry.

## Where to edit the rubric
Only `config.yaml`: roles, criteria, weights, `thresholds` (shortlist/maybe cutoffs), prompt template, sheet/Coda column names, model. The model scores skills/education/experience/projects; the **total is computed in code from your weights** and the **recommendation is derived in code from thresholds**.

## Debugging a failed row
Check the `Error Note` in Coda and `logs/run_<date>.jsonl` (also uploaded as a GitHub Actions artifact). Typical causes: file not shared with the service account, corrupt file, scanned CV with no OCR binaries, role name not matching a key under `roles:`.

## Dataset
No public dataset was used. The ~35 test applicants are synthetic CVs (PDF/DOCX/scanned PDF, plus deliberately corrupt and empty files) generated for this project, so there are no licensing or privacy concerns. They deliberately cover all five roles, strong/average/weak candidates, mixed file formats and failure cases.
