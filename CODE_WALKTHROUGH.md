# Code Walkthrough (line by line)

Order: how data flows. `run.py` calls everything else, so start there for the big picture, then read the `src/` files in the order they are used.

Quick glossary
- **dict** = key/value pairs, e.g. `{"name": "Sneha"}`. **list** = ordered items. **set** = unique items, fast "is it in here?" checks.
- **API** = a web address you send requests to and get data back from (Coda, Groq, Google).
- **try / except** = "attempt this; if it crashes, run the except block instead of stopping the program".
- A function starting with `_` (e.g. `_pdf`) is a private helper used only inside its own file.

---

## 1. `src/config.py` (loads settings)

| Lines | Explanation |
| --- | --- |
| 1-4 | Imports: `os` reads environment variables, `re` is regular expressions (pattern matching), `yaml` reads `config.yaml`, `load_dotenv` reads the `.env` file. |
| 6 | `load_dotenv()` copies every `KEY=value` line in `.env` into environment variables. On GitHub there is no `.env`; the secrets are already environment variables, so this does nothing there. |
| 9 | `load_config(path="config.yaml")` defines a function that reads the config; the default file is `config.yaml`. |
| 10-11 | Opens the file as UTF-8 text and parses the YAML into a Python dict called `cfg`. |
| 12 | Sets the Coda doc ID: use the `CODA_DOC_ID` environment variable if it exists, otherwise the value in `config.yaml`. `A or B` means "A if it is non-empty, else B". |
| 13 | Same for the Coda table ID. |
| 14 | Try to get the sheet ID from the `GOOGLE_SHEET_ID` environment variable. |
| 15-17 | If that is empty, pull the ID out of the sheet URL in `config.yaml`. The ID is the text after `/d/`. `re.search` finds it; `m.group(1)` is the matched ID; if no match, `None`. |
| 18 | Stores the final sheet ID in `cfg["sheet"]["id"]` so other files can use it. |
| 19 | Returns the finished config dict. |

---

## 2. `src/google_auth.py` (logs in to Google)

| Lines | Explanation |
| --- | --- |
| 1-3 | Imports `json`, `os`, and the `Credentials` class that builds a login from a service-account key. |
| 5-8 | `SCOPES` = what the login is allowed to do. Here: read Google Sheets and read Google Drive, nothing else (read-only is why uploading earlier failed). |
| 11 | `get_credentials()` returns a ready-to-use Google login. |
| 12 | Docstring: explains the two places the key can come from. |
| 13 | Looks for the whole key file contents in the env var `GOOGLE_SERVICE_ACCOUNT_JSON` (used on GitHub). |
| 14-15 | If found, parse it from JSON text and build the login directly from it. |
| 16 | Otherwise get a file path from `GOOGLE_SERVICE_ACCOUNT_FILE`, defaulting to `applicant-scoring-pipeline.json` (used on your PC). |
| 17-19 | If that file does not exist, stop with a clear message. This is the error you hit on GitHub, now with a helpful explanation. |
| 20 | Builds the login from the file and returns it. |

---

## 3. `src/sheet_reader.py` (reads the Google Sheet)

| Lines | Explanation |
| --- | --- |
| 1-2 | `gspread` is the library for Google Sheets; also imports the login function from `google_auth.py` (the dot means "same folder"). |
| 5 | `read_applicants(cfg)` returns a list of applicants. |
| 6 | Logs in to Google Sheets with the service account. |
| 7 | Opens the spreadsheet by its ID. |
| 8 | Picks the tab: the one named in `config.yaml` if given, otherwise the first tab. |
| 9 | `cols` = the column names from the config (Name, Email, Role, CV Link), so you can rename columns without code changes. |
| 10 | Empty list that will hold the applicants. |
| 11 | `ws.get_all_records()` returns each row as a dict keyed by the header row. `enumerate(..., start=2)` numbers them from 2, because row 1 is the header, so `i` matches the real sheet row number. |
| 12-18 | For each row, builds a clean dict: `rec.get(column, "")` safely fetches the value (empty if missing), `str()` makes sure it is text, `.strip()` removes spaces at both ends. |
| 19 | Returns only rows where at least one of name, email, CV link is filled, so blank rows are ignored. |

---

## 4. `src/coda_writer.py` (talks to Coda)

| Lines | Explanation |
| --- | --- |
| 1-4 | Imports: `json` (convert dict to text), `os`, `requests` (send web requests), `datetime` (timestamps). |
| 6 | `BASE` = the root address of Coda's API. |
| 9-10 | `headers()` returns the HTTP headers Coda requires: your token as `Bearer <token>` (this is the login), and the content type JSON. `os.environ[...]` crashes with a clear KeyError if the token is missing, which is intended. |
| 13-14 | `url(cfg, tail)` builds an address like `.../docs/<doc>/tables/<table>/rows`. `tail` is the last part (`rows` or `columns`). |
| 17-20 | `table_columns(cfg)` asks Coda which columns the table has. `raise_for_status()` raises an error if Coda answered with a failure code. Returns the names as a set. |
| 23-24 | `write_row(cfg, available_cols, rec)` writes one applicant. `rec` is a dict keyed by internal names such as `total_score`. |
| 25 | `names` = mapping from internal names to the real Coda column titles (from `config.yaml`). |
| 26 | Empty list of cells to write. |
| 27-30 | For each item: look up the Coda column title; only add the cell if the column is configured, actually exists in the table (this is why the optional `CV Hash` column is skipped safely), and the value is not `None`. |
| 31 | Builds the request body: the row's cells, and `keyColumns` = `["Applicant ID"]`. This is what makes it an **upsert**: Coda updates the row with the same Applicant ID instead of adding a second one. |
| 32 | Sends the POST request (30-second timeout). |
| 33-34 | Coda answers 200 or 202 (accepted) on success. Anything else raises an error that includes Coda's message. |
| 37 | `make_record(...)` turns an applicant plus score result into the dict above. |
| 38-40 | Fills the common fields: ID, name, email, role, link, current UTC time (ISO format), CV hash, error note. |
| 41-43 | If there is a scoring result: add total score, sub-scores (as JSON text), recommendation, reason, and `Status = "Scored"`. |
| 44-45 | Otherwise `Status = "Failed"` (the error note was already set above). |
| 46 | Returns the record. |

---

## 5. `src/dedup.py` (prevents duplicates)

| Lines | Explanation |
| --- | --- |
| 1-4 | Imports hashing, regex, requests, and reuses `headers` and `url` from `coda_writer.py`. |
| 7-10 | `norm_email` cleans an email for comparison: handles empty values, strips spaces, lowercases, then extracts just the `name@domain.com` part with a regex (Coda sometimes returns emails wrapped as links). If no match, returns the cleaned text. |
| 13-14 | `applicant_id`: take the cleaned email (or the CV link if there is no email), turn it to bytes with `.encode()`, compute the SHA-256 hash, convert to hex text, keep the first 12 characters. Same email always gives the same ID. |
| 17-18 | `class Existing` = a snapshot of what is already in Coda. |
| 20 | `__init__` runs when you write `Existing(cfg)`; it loads everything. |
| 21 | Column name mapping from the config. |
| 22 | Three empty sets: known IDs, known emails, known CV hashes. |
| 23 | Request settings: use column names as keys, 200 rows per page. |
| 24 | Starting address: the table's rows endpoint. |
| 25-28 | Loop over pages: GET the rows, fail loudly on error, parse the JSON. |
| 29-30 | Go through each row; `v` = that row's values by column name. |
| 31-34 | Special case: if a row is `Failed` and its error starts with "Scoring failed", ignore it so the pipeline retries it (these failed because the AI/API broke, not because the CV was bad). |
| 35-40 | Add the row's Applicant ID, email (cleaned) and CV hash to the sets if present. |
| 41 | Coda returns `nextPageLink` if more rows exist; the loop continues with it. `params` becomes `None` because that link already contains them. When there is no next page, the loop ends. |
| 43-44 | `seen_applicant`: True if the ID or the email is already known. |
| 46-47 | `seen_hash`: True if this CV content hash was seen before (and not empty). |
| 49-53 | `add`: records a newly processed applicant in the sets, so duplicates inside the same run are also caught. |

---

## 6. `src/extractor.py` (CV file to text)

| Lines | Explanation |
| --- | --- |
| 1 | Docstring: the promise of this file is that it never crashes; it always returns a result object. |
| 2-16 | Imports: hashing, in-memory file handling (`io`), regex, finding programs (`shutil`), running programs (`subprocess`), temp folders, dataclass (simple record class), Google Drive download tools, and our login. |
| 18 | `GDOC` = Google's type name for a native Google Doc. |
| 21-28 | `ExtractResult` is a small record with the outcome: `ok` (success?), `text`, `cv_hash`, `method` (how it was read), `error`, and `retryable` (True when the problem is missing tools on this machine, not a bad CV). |
| 31-36 | `_file_id` finds the Drive file ID inside a link. It tries two patterns: `/d/<id>` and `?id=<id>`. Returns `None` if neither matches. |
| 39-43 | `_drive_fetch` downloads the file. First it extracts the ID; if there is none, it raises "not a recognisable link". |
| 44-46 | Try the service account first: build a Drive client and fetch the file's type and name. |
| 47-50 | If it is a native Google Doc, request a plain-text export; otherwise request the raw file bytes. |
| 51-55 | Download in chunks into memory (`BytesIO`) until finished. |
| 56 | Returns the bytes, plus True if it was a Google Doc export. |
| 57-59 | If Google answered with an error other than 403/404 (for example a network problem), re-raise it; 403 (no permission) and 404 (not found) fall through to the public fallback. |
| 60 | Fallback: try Drive's public download address (works if the file is "anyone with the link"). |
| 61-62 | If the response is an error, or is an HTML web page (Google's sign-in / virus-scan page) instead of a file, raise a "not shared" error. |
| 63 | Otherwise return the downloaded bytes. |
| 66-76 | `_sniff` looks at the first bytes of the file (its "magic number") to learn the real type, regardless of the file name. `%PDF` = PDF, `PK` = DOCX (a zip file), `D0CF11E0...` = old .doc, PNG/JPEG/TIFF/BMP signatures = image, anything else = plain text. |
| 79-81 | `_ocr_images`: runs Tesseract OCR on each image and joins the text with line breaks. Imported inside the function so the file still loads if the library is missing. |
| 84-88 | `_pdf`: opens the PDF from memory and joins the text of every page (`or ""` for pages without text). Returns the text plus the method name. |
| 91-93 | `_pdf_ocr`: converts the first 6 pages to images at 200 dpi (needs Poppler) and OCRs them. Used for scanned PDFs. |
| 96-103 | `_docx`: opens the Word file, collects every paragraph, then every table row (cells joined by spaces), and joins them. |
| 106-116 | `_doc` (old .doc): find LibreOffice; if absent raise an error; otherwise write the bytes to a temp folder, run LibreOffice in the background to convert to .docx, then read that with `_docx`. The temp folder is auto-deleted. |
| 119-121 | `_image`: opens the image and OCRs it. |
| 124-130 | `_txt`: tries to decode the bytes as UTF-8, then UTF-16, then Latin-1; returns empty text if none works. |
| 133 | `extract(link, min_chars=80)` is the main function; text shorter than `min_chars` counts as "no text". |
| 134-137 | Try to download. If it fails for any reason, return a failure result with the reason (capped to 400 chars). |
| 138-139 | A 0-byte file returns "Empty file". |
| 140 | Computes the SHA-256 hash of the file bytes (used for the duplicate-CV check). |
| 141-143 | If it was a Google Doc export, just decode the text. |
| 144-151 | Otherwise detect the type. For PDFs: read the text layer; if it is too short (a scan), fall back to OCR. For everything else, pick the matching reader function from a small lookup table and call it. |
| 152-154 | If reading crashed: when the error is about missing tools (Poppler, Tesseract, LibreOffice), return `retryable=True` so the pipeline defers the row instead of marking it Failed. |
| 155-156 | Any other crash means the file is corrupt or unsupported: return a Failed result with the error. |
| 157-160 | Trim the text. If it is shorter than `min_chars`, return a "too short/empty" failure. |
| 161 | Success: return the text, the hash and the method used. |

---

## 7. `src/scorer.py` (asks the AI to score)

| Lines | Explanation |
| --- | --- |
| 1-3 | Imports `json`, `os`, and the `Groq` client library. |
| 5-6 | `SCHEMA` = the exact JSON shape we tell the model to return. |
| 7 | `KEYS` = the four sub-scores we require. |
| 8 | `MAX_CV_CHARS` = at most 12,000 characters of CV are sent, to stay inside model limits. |
| 11-14 | `recommend`: at or above `shortlist_min` is Shortlist; otherwise at or above `maybe_min` is Maybe; otherwise Reject. Thresholds come from `config.yaml`. |
| 17-18 | `build_prompt` fetches the rubric block for this role. |
| 19-25 | Fills the `prompt_template` from the config: role name, criteria as a bullet list, the weights as JSON, the schema, and the CV text (cut to the limit). |
| 28-29 | `_parse` converts the model's reply text into a dict (`json.loads` raises an error if it is not valid JSON). |
| 30 | For each of the four sub-scores: convert to a number and clamp between 0 and 100, so absurd values like 150 are impossible. |
| 31 | Sum of the weights (falls back to 1 to avoid dividing by zero). |
| 32 | **Total score** = weighted average of the sub-scores, rounded to 1 decimal. Calculated in code, not by the AI. |
| 33-35 | Returns total, sub-scores, a recommendation derived from the thresholds (not from the model's own word), and the reason (max 1000 chars). |
| 38-39 | `score(cfg, role, cv_text)` returns `(result, error)`; exactly one of them is empty. |
| 40 | Creates the Groq client using your key. |
| 41 | Builds the prompt. |
| 42 | `last` remembers the most recent error message. |
| 43 | Loops over two attempts: the configured temperature (0.2), then temperature 0 (most predictable). |
| 44-48 | Sends the request: chosen model, the temperature, `response_format=json_object` (forces valid JSON output), and the prompt as a user message. |
| 49 | Parses the reply and returns the result with an empty error, ending the function on success. |
| 50-51 | If anything failed (API error, invalid JSON, missing field), save the error and try the next attempt. |
| 52 | If both attempts fail, return no result plus "Scoring failed after retry: ...". The dedup file looks for this exact start text to know the row can be retried. |

---

## 8. `run.py` (the conductor)

| Lines | Explanation |
| --- | --- |
| 1 | Docstring: one-sentence summary of the whole pipeline. |
| 2-6 | Standard imports: JSON, OS, `sys` (exit codes), `time` (pauses), and date/time tools. |
| 8-13 | Imports the functions from the `src/` files. |
| 16-21 | `resolve_role`: matches the sheet's role text to a role in the config, ignoring case and spaces. Matches either the role's main name or any alias (this is how "ML Intern" maps to "Machine Learning Intern"). Returns the config role name, or `None`. |
| 24 | `main()` contains the whole run. |
| 25 | Loads the config. |
| 26 | Creates the `logs` folder if it does not exist. |
| 27 | Log file name using today's UTC date, e.g. `logs/run_2026-11-14.jsonl`. |
| 29-34 | `log(...)`: a helper that appends one JSON line (time, applicant ID, status, error) to the log file and also prints it on screen as `[status] id error`. Defined inside `main` so it can use `log_path`. |
| 36 | Reads all applicants from the Google Sheet. |
| 37 | Gets the Coda column names that actually exist. |
| 38 | Loads what is already in Coda (the dedup snapshot). |
| 39 | Prints how many sheet rows exist and how many IDs are already in Coda. |
| 40 | Counters for the final summary. |
| 42 | Starts the loop: one pass per applicant. |
| 43 | Computes this applicant's ID from their email. |
| 44 | `try:` starts protection, so any crash inside affects only this applicant. |
| 45-48 | If the applicant is already in Coda: count as skipped, log it, and `continue` (jump to the next applicant). |
| 50 | Starts with empty hash, result and error. |
| 51-52 | No email, or no `@`: set the error "Missing or invalid email" (the row will be written as Failed). |
| 53-54 | Role not in the config (even via aliases): error "Unknown role". |
| 55-56 | Otherwise: download and read the CV. |
| 57 | Remembers the CV hash. |
| 58-61 | If the failure is only because OCR tools are missing: log "Deferred", count as skipped, and move on without writing anything to Coda, so a later run (e.g. on GitHub) retries it. |
| 62-63 | If extraction failed (corrupt, empty): keep its error to be written as Failed. |
| 64-67 | If this exact CV file content was already scored for someone else: skip it as a duplicate. |
| 68-69 | Otherwise send the text to the AI. `score` gives back a result or an error. |
| 71 | Builds the Coda record and writes (upserts) it. This runs for both successes and failures, so every applicant leaves a row. |
| 72 | Adds the applicant to the in-memory snapshot so duplicates later in this same run are caught. |
| 73-74 | Status is "Scored" if there was a result, else "Failed"; update the counter. |
| 75 | Logs the outcome. |
| 76 | Waits half a second to avoid hitting rate limits on Groq/Coda. |
| 77-79 | `except`: an unexpected crash. Counts a failure and logs the error type and message. |
| 80-82 | Tries to write a Failed row for it to Coda too, so nothing silently vanishes. |
| 83-84 | If even that write fails, log "WriteFailed" and move on. |
| 86 | After the loop: prints the summary, e.g. `Done: {'Scored': 8, 'Failed': 0, 'Skipped': 31}`. |
| 87 | Returns 0 = success exit code. |
| 90-91 | `if __name__ == "__main__":` runs `main()` only when you start this file directly (not when another file imports it). `sys.exit(...)` passes the exit code to the system. |

---

## Big picture in five sentences
1. `run.py` loads the config, the sheet, and a snapshot of Coda.
2. For each applicant it checks `dedup` (skip if known).
3. It downloads and reads the CV with `extractor` (never crashing).
4. It sends the text to Groq through `scorer`, where the code, not the AI, decides total score and recommendation.
5. It upserts the outcome (Scored or Failed) into Coda with `coda_writer` and logs it.
