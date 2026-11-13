# Daily Applicant Scoring Pipeline — Implementation Spec

By Claude, for the Intern Project brief

## 1. Goal

Build a daily pipeline that reads new applicants from a Google Sheet, scores each CV with AI against a rubric, and writes one row per applicant into a Coda table — with no duplicates, graceful handling of bad CVs, and a single config file that controls the rubric, weights, and target sheet/table without code changes.

## 2. Architecture

```
[GitHub Actions cron, daily]
          |
          v
[run.py] --reads config.yaml-->  [Google Sheet]
          |                         (applicants: name, email, role, CV link)
          v
[dedup.py] --checks against--> [Coda table: existing emails/hashes]
          |
          v  (new rows only)
[extractor.py] -- pulls raw text from CV (pdf/docx/doc/txt/image/gdoc link)
          |
          v
[scorer.py] -- sends rubric + CV text to Groq LLM --> {score, sub-scores, recommendation, reason}
          |
          v
[coda_writer.py] -- POSTs one row to Coda table (Status: Scored or Failed)
          |
          v
[run_log.jsonl] -- append-only log of every row processed, per run
```

One row's failure (bad file, OCR failure, API error) is caught, logged, and written to Coda with `Status=Failed` + `Error note`; the run continues to the next applicant.

## 3. Data source (what to turn into the Google Sheet)

Recommended: a public resume/CV dataset, e.g. Kaggle's "Resume Dataset" (categorized resumes as text) or a public job-board export. Pick one with real CV *files* (PDF/text) rather than only structured fields, so the scoring module has something realistic to parse.

Plan:

- Download ~40-50 sample CVs (mix of formats: PDF, DOCX, TXT; include a few scanned/image CVs and 2-3 deliberately broken files: corrupt PDF, empty file, non-English CV).
- Upload CV files to a Google Drive folder, set link sharing to "anyone with link can view."
- Build the Google Sheet with columns: `Name`, `Email`, `Role`, `CV Link`.
- Document in the README which dataset was used and why (license, availability, realistic file diversity).

## 4. Google Sheet schema

| Column | Notes |
| --- | --- |
| Name | free text |
| Email | used as the dedup key |
| Role | must match a role key in `config.yaml` → `roles:` |
| CV Link | Google Drive file link, or Google Doc link |

Column *names* are configurable — see `config.yaml` → `sheet.columns` — so a real deployment can point at differently-named columns with no code change.

## 5. Dedup strategy

- Primary key: **email**, lowercased and trimmed.
- Secondary guard: **sha256 hash of the CV file bytes** (or of the extracted text, if the CV link is a Google Doc with no stable byte content) — catches the same person re-applying under a slightly different email, or protects against an email typo causing a duplicate.
- Before scoring a sheet row, the pipeline queries the Coda table for any existing row where `Email` matches or `CV Hash` (stored in a hidden/internal column, or encoded into `Applicant ID`) matches. If found, skip.
- `Applicant ID` = `sha256(email)[:12]` — deterministic, so re-running never creates a second row for the same applicant even if Coda's own row order changes.

## 6. Scoring module (`scorer.py` + `extractor.py`)

**Extraction (`extractor.py`)** — input: CV link + declared/sniffed file type. Output: plain text, or a structured "extraction failed" result.

| Format | Method |
| --- | --- |
| PDF | `pdfplumber` (text layer) |
| DOCX | `python-docx` |
| DOC (legacy) | `textract` or convert via `libreoffice --headless --convert-to docx` then `python-docx` |
| TXT | read directly |
| Image / scanned PDF | `pytesseract` OCR (render PDF pages to images with `pdf2image` first if needed) |
| Google Doc link | Google Docs API, export as plain text |

If extraction yields empty/near-empty text, or the file can't be opened at all (corrupt), return `status=Failed`, `error_note="<reason>"` — never raise/crash the run.

Non-English CVs: pass extracted text to the LLM as-is; the prompt instructs the model to score in the CV's own language context and note in `reason` if the CV language made scoring harder — not to fail outright.

**Scoring (`scorer.py`)** — input: extracted text + the `roles[<role>]` rubric block from `config.yaml`. Calls Groq's chat completion API (model e.g. `llama-3.3-70b-versatile`) with a prompt built from the config's rubric and criteria, asking for **strict JSON** output:

```json
{
  "total_score": 0-100,
  "sub_scores": {"skills": 0-100, "education": 0-100, "experience": 0-100, "projects": 0-100},
  "recommendation": "Shortlist|Maybe|Reject",
  "reason": "1-3 sentences"
}
```

`recommendation` is also re-derived in code from `total_score` vs. `config.yaml` → `thresholds`, so a model formatting slip never silently changes a hiring decision. JSON parsing is wrapped in try/except with one retry (lower temperature) before marking the row `Failed`.

## 7. `config.yaml` (single source of truth)

```yaml
sheet:
  url: "<google_sheet_url>"
  columns:
    name: "Name"
    email: "Email"
    role: "Role"
    cv_link: "CV Link"

coda:
  doc_id: "<coda_doc_id>"
  table_id: "<coda_table_id>"

thresholds:
  shortlist_min: 80
  maybe_min: 55   # below this -> Reject

roles:
  "Automation Intern":
    weights:
      skills: 0.3
      education: 0.15
      experience: 0.3
      projects: 0.25
    criteria:
      - "Experience with workflow automation and process optimization"
      - "Skills match: Python, REST APIs, webhooks, automation tools (n8n, Zapier, Make)"
      - "Ability to integrate third-party services and handle data efficiently"
      - "Problem-solving skills and evidence of automating repetitive tasks"
      - "Clarity of writing and documentation in the CV"
      - "Grammar and spelling quality"

  "Backend Intern":
    weights:
      skills: 0.3
      education: 0.15
      experience: 0.35
      projects: 0.2
    criteria:
      - "Relevant backend development experience through internships or projects"
      - "Skills match: Python, Java, Node.js, REST APIs, SQL/NoSQL databases"
      - "Understanding of authentication, authorization and API development"
      - "Knowledge of database design, query optimization and server-side logic"
      - "Clarity of writing and documentation in the CV"
      - "Grammar and spelling quality"
  "Data Analyst Intern":
    weights:
      skills: 0.35
      education: 0.15
      experience: 0.3
      projects: 0.2
    criteria:
      - "Skills match: SQL, Python, Excel, Power BI, Tableau"
      - "Knowledge of data cleaning, preprocessing and exploratory data analysis"
      - "Understanding of statistics and analytical techniques"
      - "Experience with data visualization and dashboard development"
      - "Projects demonstrating data analysis and actionable insights"
      - "Ability to communicate findings through clear reports and documentation"
      - "Grammar and spelling quality"

  "Machine Learning Intern":
    weights:
      skills: 0.35
      education: 0.15
      experience: 0.25
      projects: 0.25
    criteria:
      - "Skills match: Python, NumPy, Pandas, Scikit-learn, TensorFlow or PyTorch"
      - "Understanding of supervised and unsupervised machine learning algorithms"
      - "Knowledge of statistics, probability and model evaluation metrics"
      - "Experience with data preprocessing, feature engineering and model training"
      - "Projects demonstrating practical machine learning implementation"
      - "Understanding of model deployment and API integration"
      - "Grammar and spelling quality"
  
  "Full Stack Developer Intern":
    weights:
      skills: 0.35
      education: 0.1
      experience: 0.3
      projects: 0.25
    criteria:
      - "Skills match: HTML, CSS, JavaScript, React.js and Node.js"
      - "Knowledge of REST APIs and frontend-backend integration"
      - "Database experience with MongoDB, MySQL or PostgreSQL"
      - "Understanding of authentication, authorization and application security"
      - "Experience building responsive and functional web applications"
      - "Projects demonstrating end-to-end full stack development"
      - "Grammar and spelling quality"

prompt_template: |
  You are screening a CV for the role of {role}.
  Score against these criteria: {criteria}
  Weights: {weights}
  Return strict JSON only, matching this schema: {schema}
  CV text:
  {cv_text}
```

Changing a cutoff or adding a criterion = editing this file only — this is what the "live change" walkthrough will demonstrate.

## 8. Coda table

Columns (created once, by a one-time setup script `setup_coda_table.py`, or manually): `Applicant ID`, `Name`, `Email`, `Role`, `CV Link`, `Total Score`, `Sub-scores` (JSON as text), `Recommendation`, `Reason`, `Date Processed`, `Status`, `Error Note`.

Writes use the Coda API `POST /docs/{docId}/tables/{tableId}/rows` with `keyColumns: ["Applicant ID"]` so a re-run that somehow reaches the write step twice **upserts** rather than duplicating.

## 9. Daily schedule

GitHub Actions workflow `.github/workflows/daily_run.yml`:

```yaml
on:
  schedule:
    - cron: "0 7 * * *"   # 07:00 UTC daily
  workflow_dispatch: {}      # manual trigger for the demo/live change
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -r requirements.txt
      - run: python run.py
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          CODA_API_TOKEN: ${{ secrets.CODA_API_TOKEN }}
          GOOGLE_SERVICE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
```

`workflow_dispatch` lets you trigger it on demand during the 20-minute walkthrough.

## 10. Secrets

Locally: a `.env` file (never committed — add to `.gitignore` immediately) holding:

```
GROQ_API_KEY=...
CODA_API_TOKEN=...
GOOGLE_SERVICE_ACCOUNT_FILE=credentials.json
GOOGLE_SHEET_ID=...
CODA_DOC_ID=...
CODA_TABLE_ID=...
```

In CI: the same values go into GitHub repo **Settings → Secrets and variables → Actions**, not into any committed file.

> Note on the keys you pasted above: every value you gave was a placeholder (`your_key`, `your_coda_token`, etc.), not an actual credential, so nothing sensitive was exposed here. When you generate the real ones: put them straight into `.env` (gitignored) and GitHub Actions secrets, never into a chat, a committed file, or `config.yaml`. Rotate any key that *does* ever touch a chat, a public repo, or a shared doc, since it should be treated as compromised the moment it's pasted somewhere outside its intended secret store.

## 11. Error handling & logging

- Every row processed (success or failure) gets one JSON line appended to `logs/run_YYYY-MM-DD.jsonl`: `{timestamp, applicant_id, status, error}`.
- A failed row still gets written to Coda (`Status=Failed`, `Error Note` filled) so nothing silently vanishes from the table.
- Top-level run wrapped in try/except per applicant — one bad CV never aborts the batch.

## 12. Suggested repo structure

```
/├── run.py                  # orchestrates one daily run
├── config.yaml
├── requirements.txt
├── .gitignore              # .env, credentials.json, logs/
├── .github/workflows/daily_run.yml
├── src/
│   ├── sheet_reader.py     # Google Sheets -> list of applicant rows
│   ├── dedup.py            # checks Coda for existing Applicant ID
│   ├── extractor.py        # CV file/link -> plain text
│   ├── scorer.py           # text + rubric -> Groq call -> parsed result
│   └── coda_writer.py      # upsert row into Coda
├── setup_coda_table.py     # one-time: creates the Coda table/columns
├── logs/
└── README.md
```

## 13. Tech stack

Python 3.11, `gspread` + `google-auth` (Sheets), `requests` (Coda REST), `groq` (official Python client), `pdfplumber`, `python-docx`, `pytesseract` + `pdf2image` (OCR), `pyyaml`, `python-dotenv`.

## 14. Testing plan (covers the "at least 30 scored applicants" deliverable)

- ~30 normal CVs across the roles defined in `config.yaml`.
- 3 corrupt/unreadable file → expect `Status=Failed`, clear `Error Note`.
- 2 scanned image CV → expect OCR path taken, scored normally (verify in logs).
- 1 empty file → expect `Status=Failed`.
- Run the pipeline twice back-to-back → verify Coda row count is unchanged after the second run (dedup proof).

## 15. Deliverables checklist (from the brief)

- [ ] Repo + README (setup, daily-run explanation, where to edit the rubric, how to debug a failed row)
- [ ] One-page architecture sketch (the diagram in §2, cleaned up)
- [ ] Coda table with 30+ scored applicants incl. bad CVs
- [ ] 20-minute walkthrough + one live change (e.g., add a criterion or move `shortlist_min` in `config.yaml`, re-run via `workflow_dispatch`, show the new Coda rows)

## Open decisions for you

- Which public CV dataset to actually use (pick one with real files, not just text fields)
- Exact wording of the LLM rubric prompt per role
- Whether to add one of the optional extras (duplicate-flagging, Slack/email daily summary, or name/photo stripping for bias reduction) — all three slot into `run.py` as an extra step after scoring, with no architecture change needed
