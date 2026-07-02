"""
Balochistan High Court (BHC) Judgment Scraper
=============================================
Downloads all judgment PDFs from https://portal.bhc.gov.pk/judgments/
by iterating over every judge (Search by Judge), fetching all records
from 01/01/2005 to today, and downloading the files.

API:
  - Login:      POST https://api.bhc.gov.pk/login
  - Judges:     POST https://api.bhc.gov.pk/v2/judges
  - Judgments:  POST https://api.bhc.gov.pk/v2/judgments   (body: {judgeId, sDate, eDate, searchBy:3})
  - Download:   GET  https://api.bhc.gov.pk/v2/downloadpdf/{FOLDER}/{NAME}.{EXT}
"""

import os
import re
import csv
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

# ─── Configuration ────────────────────────────────────────────────────────────
API_BASE          = "https://api.bhc.gov.pk"
GUEST_EMAIL       = "guest@bhc.gov.pk"
GUEST_PASSWORD    = "4td!pBJ4mk+dV-2b"

DOWNLOAD_DIR      = os.environ.get("DOWNLOAD_DIR", "data_warehouse/raw/bhc")
METADATA_FILE     = os.environ.get("METADATA_FILE", "data_warehouse/raw/bhc/metadata.csv")

FROM_DATE         = "2005-01-01"          # API accepts YYYY-MM-DD
TO_DATE           = str(date.today())     # Today

MAX_WORKERS       = 3                     # Parallel download threads
DELAY_PER_THREAD  = 1.0                   # Seconds between requests per thread
REQUEST_TIMEOUT   = 60                    # Seconds

# ─── Session + Retry Setup ────────────────────────────────────────────────────
session = requests.Session()

retry_strategy = Retry(
    total=5,
    backoff_factor=2.0,
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = HTTPAdapter(
    max_retries=retry_strategy,
    pool_connections=MAX_WORKERS + 1,
    pool_maxsize=MAX_WORKERS + 1,
)
session.mount("https://", adapter)
session.mount("http://",  adapter)

print_lock   = threading.Lock()
token_lock   = threading.Lock()
_auth_token  = None   # Filled after login


def login() -> str:
    """Authenticate with BHC API and return a Bearer token."""
    resp = session.post(
        f"{API_BASE}/login",
        json={"email": GUEST_EMAIL, "password": GUEST_PASSWORD},
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError(f"Login failed – no access_token in response: {resp.text[:200]}")
    return token


def get_token() -> str:
    """Return the current auth token, refreshing if needed."""
    global _auth_token
    with token_lock:
        if _auth_token is None:
            _auth_token = login()
    return _auth_token


def refresh_token() -> str:
    """Force-refresh the auth token (call on 401)."""
    global _auth_token
    with token_lock:
        _auth_token = login()
    return _auth_token


def auth_headers() -> dict:
    return {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type":  "application/json",
        "Accept":        "application/json",
    }


def sanitize_filename(name: str) -> str:
    """Strip characters that are illegal in file names."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()


# ─── API Calls ────────────────────────────────────────────────────────────────

def fetch_judges() -> list:
    """Return list of all judges: [{JUDGE_ID, JUDGE_NAME, TOTAL_ORDERS}, ...]"""
    resp = session.post(
        f"{API_BASE}/v2/judges",
        headers=auth_headers(),
        json={},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_judgments_for_judge(judge_id: int) -> list:
    """Return all judgment records for a given judge between FROM_DATE and TO_DATE."""
    payload = {
        "judgeId":  judge_id,
        "sDate":    FROM_DATE,
        "eDate":    TO_DATE,
        "searchBy": 3,          # 3 = Search By Judge
    }
    resp = session.post(
        f"{API_BASE}/v2/judgments",
        headers=auth_headers(),
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code == 401:
        refresh_token()
        resp = session.post(
            f"{API_BASE}/v2/judgments",
            headers=auth_headers(),
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
    resp.raise_for_status()
    return resp.json()


# ─── Download Logic ───────────────────────────────────────────────────────────

def download_judgment(item: dict, row_num: int, total: int) -> dict:
    """Download a single judgment file. Returns enriched item dict with status."""
    file_id     = item["FILE_ID"]
    folder      = item["FILE_FOLDER"]
    raw_name    = item["FILE_NAME"]
    ext         = item["FILE_EXT"]
    judge_name  = sanitize_filename(item.get("AUTHOR_JUDGE", "Unknown")[:60])
    case_title  = sanitize_filename(item.get("CASE_TITLE",   "")[:60])
    reg_no      = sanitize_filename(item.get("REGISTER_NUMBER", ""))
    order_date  = item.get("ORDER_DATE", "")

    # The API always serves application/pdf regardless of FILE_EXT (often 'doc').
    # Always save as .pdf to reflect the actual content type.
    filename  = f"{folder}_{raw_name}.pdf"
    dest_path = os.path.join(DOWNLOAD_DIR, filename)

    # If an old misnamed .doc file exists, rename it so we don't re-download.
    old_path = os.path.join(DOWNLOAD_DIR, f"{folder}_{raw_name}.{ext}")
    if not os.path.exists(dest_path) and os.path.exists(old_path) and os.path.getsize(old_path) > 0:
        os.rename(old_path, dest_path)

    # Skip if already downloaded and non-empty
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        with print_lock:
            print(f"[{row_num}/{total}] Skip (exists): {filename}")
        return {**item, "filename": filename, "status": "skipped"}

    time.sleep(DELAY_PER_THREAD)

    url = f"{API_BASE}/v2/downloadpdf/{folder}/{raw_name}.{ext}"

    def _do_request(tok):
        return session.get(
            url,
            headers={"Authorization": f"Bearer {tok}"},
            timeout=REQUEST_TIMEOUT,
            stream=True,
        )

    try:
        resp = _do_request(get_token())
        if resp.status_code == 401:
            resp = _do_request(refresh_token())

        if resp.status_code == 200:
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
            with print_lock:
                print(f"[{row_num}/{total}] OK: {filename}")
            return {**item, "filename": filename, "status": "success"}
        else:
            with print_lock:
                print(f"[{row_num}/{total}] HTTP {resp.status_code}: {url}")
            return {**item, "filename": filename, "status": f"failed_http_{resp.status_code}"}

    except Exception as exc:
        with print_lock:
            print(f"[{row_num}/{total}] Error {url}: {exc}")
        return {**item, "filename": filename, "status": f"error_{exc}"}


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    # 1. Login
    print("Logging in to BHC API...")
    get_token()
    print("Login successful.\n")

    # 2. Fetch judges
    print("Fetching list of judges...")
    judges = fetch_judges()
    print(f"Found {len(judges)} judges.\n")

    # 3. Collect all judgment records across all judges (deduplicate by FILE_ID)
    print(f"Fetching judgments from {FROM_DATE} to {TO_DATE} for each judge...")
    all_items_by_id: dict = {}   # FILE_ID -> item dict

    for j in judges:
        judge_id   = j["JUDGE_ID"]
        judge_name = j["JUDGE_NAME"]
        try:
            items = fetch_judgments_for_judge(judge_id)
            new_count = 0
            for item in items:
                fid = item["FILE_ID"]
                if fid not in all_items_by_id:
                    all_items_by_id[fid] = item
                    new_count += 1
            print(f"  {judge_name}: {len(items)} records ({new_count} new, {len(items)-new_count} already seen)")
        except Exception as exc:
            print(f"  ERROR fetching judgments for {judge_name} (ID={judge_id}): {exc}")

    all_items = list(all_items_by_id.values())
    total     = len(all_items)
    print(f"\nTotal unique judgments to download: {total}\n")

    if total == 0:
        print("Nothing to download. Exiting.")
        return

    # 4. Download files
    print(f"Starting downloads with {MAX_WORKERS} threads, {DELAY_PER_THREAD}s delay per thread...\n")

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_item = {
            executor.submit(download_judgment, item, idx + 1, total): item
            for idx, item in enumerate(all_items)
        }
        try:
            for future in as_completed(future_to_item):
                res = future.result()
                if res:
                    results.append(res)
        except KeyboardInterrupt:
            print("\nInterrupted! Saving progress...")
            executor.shutdown(wait=False, cancel_futures=True)

    # 5. Write metadata CSV
    print(f"\nWriting metadata to {METADATA_FILE}...")
    fieldnames = [
        "FILE_ID", "FILE_FOLDER", "FILE_NAME", "FILE_EXT",
        "CASE_ID", "CASE_TITLE", "REGISTER_NUMBER",
        "AUTHOR_JUDGE", "TYPE_NAME", "ORDER_DATE",
        "filename", "status",
    ]
    results.sort(key=lambda x: x.get("FILE_ID", 0))
    with open(METADATA_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    # 6. Summary
    success  = sum(1 for r in results if r.get("status") == "success")
    skipped  = sum(1 for r in results if r.get("status") == "skipped")
    failed   = sum(1 for r in results if r.get("status", "").startswith(("failed", "error")))

    print(f"\nDone!")
    print(f"  Downloaded : {success}")
    print(f"  Skipped    : {skipped}")
    print(f"  Failed     : {failed}")
    print(f"  Total      : {total}")
    print(f"\nFiles saved to '{DOWNLOAD_DIR}/'")
    print(f"Metadata saved to '{METADATA_FILE}'")


if __name__ == "__main__":
    main()
