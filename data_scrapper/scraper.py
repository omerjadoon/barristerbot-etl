import os
import re
import csv
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from bs4 import BeautifulSoup

# Configuration
BASE_URL = "https://www.peshawarhighcourt.gov.pk/PHCCMS/reportedJudgments.php?action=search"
DOWNLOAD_DIR = "downloads"
METADATA_FILE = "metadata.csv"
MAX_WORKERS = 1  # Set to 1 for strict sequential downloading with delay, or higher for parallel.
DELAY_BETWEEN_REQUESTS = 1.5  # Delay in seconds between requests to avoid rate limits

# Headers to act as a normal browser
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# Create a shared requests Session with retries and connection pooling
session = requests.Session()
session.headers.update(HEADERS)

# Set up retries with exponential backoff
retry_strategy = Retry(
    total=5,
    backoff_factor=2.0,  # Wait 2s, 4s, 8s... between retries
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = HTTPAdapter(
    max_retries=retry_strategy, 
    pool_connections=MAX_WORKERS, 
    pool_maxsize=MAX_WORKERS
)
session.mount("https://", adapter)
session.mount("http://", adapter)

# Threading lock for printing and sleeping safely if multi-threaded
import threading
import time
print_lock = threading.Lock()

def sanitize_filename(filename):
    """Sanitize the filename to prevent file system issues."""
    return re.sub(r'[\\/*?:"<>|]', "", filename)

def download_pdf(pdf_info):
    """Download a single PDF and save it using the session pool."""
    url = pdf_info['url']
    row_num = pdf_info['row_num']
    title = pdf_info['title']
    
    # Try to extract filename from URL
    parsed_url = urllib.parse.urlparse(url)
    original_filename = os.path.basename(parsed_url.path)
    
    if not original_filename.endswith('.pdf'):
        # Fallback filename using row number and sanitized title
        sanitized_title = sanitize_filename(title[:50])
        original_filename = f"judgment_{row_num}_{sanitized_title}.pdf"
        
    dest_path = os.path.join(DOWNLOAD_DIR, original_filename)
    
    # Check if file already exists (for resume capability)
    if os.path.exists(dest_path):
        if os.path.getsize(dest_path) > 0:
            with print_lock:
                print(f"[{row_num}/5761] Already exists: {original_filename}")
            return {**pdf_info, 'filename': original_filename, 'status': 'skipped (exists)'}

    # Optional sleep/delay between requests
    if DELAY_BETWEEN_REQUESTS > 0:
        time.sleep(DELAY_BETWEEN_REQUESTS)

    try:
        # Use session to leverage connection pooling and keep-alive
        response = session.get(url, timeout=30)
        if response.status_code == 200:
            with open(dest_path, 'wb') as f:
                f.write(response.content)
            with print_lock:
                print(f"[{row_num}/5761] Downloaded: {original_filename}")
            return {**pdf_info, 'filename': original_filename, 'status': 'success'}
        else:
            with print_lock:
                print(f"[{row_num}/5761] Failed (Status {response.status_code}): {url}")
            return {**pdf_info, 'filename': original_filename, 'status': f'failed_status_{response.status_code}'}
    except Exception as e:
        with print_lock:
            print(f"[{row_num}/5761] Error downloading {url}: {e}")
        return {**pdf_info, 'filename': original_filename, 'status': f'error_{str(e)}'}

def main():
    # 1. Create downloads folder
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    
    # 2. Fetch or Parse search results
    print("Fetching the reported judgments search page...")
    try:
        response = session.get(BASE_URL, timeout=60)
        response.raise_for_status()
    except Exception as e:
        print(f"Error fetching the main search page: {e}")
        print("Note: The server might have temporarily blocked your IP. Please wait a few minutes or use a VPN/Proxy.")
        return

    print("Parsing search page content...")
    soup = BeautifulSoup(response.content, 'html.parser')
    
    # Locate the target data table
    table = soup.find('table', id='employee_list')
    if not table:
        print("Could not find the table with ID 'employee_list' containing the judgments.")
        return
        
    tbody = table.find('tbody')
    if not tbody:
        print("Table contains no tbody element.")
        return
        
    rows = tbody.find_all('tr')
    print(f"Found {len(rows)} entries in the table.")
    
    # Extract judgment details and PDF links
    pdf_list = []
    for idx, row in enumerate(rows):
        cols = row.find_all('td')
        if len(cols) < 8:
            continue
            
        link_tag = row.find('a', href=True)
        if not link_tag:
            continue
            
        href = link_tag['href'].strip()
        # Clean double slashes in host/path structure if present
        if href.startswith('https://www.peshawarhighcourt.gov.pk/PHCCMS//'):
            href = href.replace('PHCCMS//', 'PHCCMS/')
            
        # Parse fields
        title = cols[1].text.strip() if len(cols) > 1 else ''
        citation = cols[3].text.strip() if len(cols) > 3 else ''
        date = cols[4].text.strip() if len(cols) > 4 else ''
        category = cols[7].text.strip() if len(cols) > 7 else ''
        
        pdf_list.append({
            'row_num': idx + 1,
            'title': title,
            'citation': citation,
            'date': date,
            'category': category,
            'url': href
        })
        
    print(f"Extracted {len(pdf_list)} valid PDF links from the webpage.")
    
    # 3. Download PDFs concurrently or sequentially
    if MAX_WORKERS > 1:
        print(f"Starting downloads using up to {MAX_WORKERS} threads (connection pool) with {DELAY_BETWEEN_REQUESTS}s delay per thread...")
    else:
        print(f"Starting downloads sequentially with {DELAY_BETWEEN_REQUESTS}s delay between requests...")
        
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(download_pdf, pdf): pdf for pdf in pdf_list}
        try:
            for future in as_completed(futures):
                res = future.result()
                if res:
                    results.append(res)
        except KeyboardInterrupt:
            print("\nDownload process interrupted by user. Writing progress down...")
            executor.shutdown(wait=False, cancel_futures=True)
                
    # 4. Save metadata index
    print("Writing metadata index to CSV...")
    fieldnames = ['row_num', 'title', 'citation', 'date', 'category', 'url', 'filename', 'status']
    with open(METADATA_FILE, mode='w', newline='', encoding='utf-8') as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        # Sort results by row_num to keep order
        results.sort(key=lambda x: x.get('row_num', 0))
        for res in results:
            writer.writerow(res)
            
    print(f"Completed! Downloaded PDFs are in '{DOWNLOAD_DIR}/' and metadata is saved to '{METADATA_FILE}'.")

if __name__ == '__main__':
    main()

