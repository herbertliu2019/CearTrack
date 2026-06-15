import os
import time
import threading
import requests
import urllib.parse
from datetime import datetime, timezone
from msal import PublicClientApplication, SerializableTokenCache
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Configuration ─────────────────────────────────
CLIENT_ID = "9bc3ab49-b65d-410a-85ad-de819febfddc"
TENANT = "https://login.microsoftonline.com/organizations"
SCOPES = ["https://cearinc.sharepoint.com/.default"]
CACHE_FILE = "/opt/testonedrive/token_cache.bin"
BASE_URL = "https://cearinc.sharepoint.com/sites/CEARITAD"

SYNC_TARGETS = [
    {
        "remote": "/sites/CEARITAD/Shared Documents/ITAD Docs/03 Testing/CPU",
        "local": "/mnt/CPU"
    },
    {
        "remote": "/sites/CEARITAD/Shared Documents/ITAD Docs/04 Data Wiping/EPS/logs",
        "local": "/mnt/WIPE"
    },
]

# ── Authentication ────────────────────────────────
cache = SerializableTokenCache()
if os.path.exists(CACHE_FILE):
    cache.deserialize(open(CACHE_FILE, "r").read())

app = PublicClientApplication(CLIENT_ID, authority=TENANT, token_cache=cache)

result = None
accounts = app.get_accounts()
if accounts:
    result = app.acquire_token_silent(SCOPES, account=accounts[0])

if not result:
    flow = app.initiate_device_flow(scopes=SCOPES)
    print(flow["message"])
    input("Login completed in browser, press Enter to continue...")
    result = app.acquire_token_by_device_flow(flow)

if cache.has_state_changed:
    open(CACHE_FILE, "w").write(cache.serialize())

token = result["access_token"]

# ── Thread-local session ──────────────────────────
thread_local = threading.local()

def get_session():
    if not hasattr(thread_local, "session"):
        s = requests.Session()
        retry = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
        s.mount("https://", HTTPAdapter(max_retries=retry))
        s.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json;odata=verbose",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        thread_local.session = s
    return thread_local.session

# ── Download single file ──────────────────────────
def download_file(f, local_path):
    local_file = os.path.join(local_path, f["Name"])
    sp_time = datetime.fromisoformat(f["TimeLastModified"].replace("Z", "+00:00"))

    if os.path.exists(local_file):
        local_mtime = datetime.fromtimestamp(os.path.getmtime(local_file), tz=timezone.utc)
        if local_mtime >= sp_time:
            return

    file_url = f"https://cearinc.sharepoint.com{urllib.parse.quote(f['ServerRelativeUrl'])}"
    print(f"Downloading: {f['ServerRelativeUrl']}")

    try:
        s = get_session()
        resp = s.get(file_url, stream=True, timeout=60)
        with open(local_file, "wb") as fp:
            for chunk in resp.iter_content(chunk_size=65536):
                fp.write(chunk)
        sp_timestamp = sp_time.timestamp()
        os.utime(local_file, (sp_timestamp, sp_timestamp))
    except Exception as e:
        print(f"  Failed: {f['Name']} - {e}")

# ── Recursive download ────────────────────────────
def download_folder(folder_path, local_path):
    os.makedirs(local_path, exist_ok=True)

    url = f"{BASE_URL}/_api/web/GetFolderByServerRelativePath(decodedurl='{folder_path}')/Files?$select=Name,ServerRelativeUrl,TimeLastModified"
    try:
        s = get_session()
        r = s.get(url, timeout=30)
        if r.status_code != 200 or not r.text:
            print(f"  Skipping (HTTP {r.status_code}): {folder_path}")
            return
        data = r.json()
    except Exception as e:
        print(f"  Skipping (error): {folder_path} - {e}")
        return

    # 并发下载文件
    files = data["d"]["results"]
    with ThreadPoolExecutor(max_workers=40) as executor:
        futures = [executor.submit(download_file, f, local_path) for f in files]
        for future in as_completed(futures):
            future.result()

    url2 = f"{BASE_URL}/_api/web/GetFolderByServerRelativePath(decodedurl='{folder_path}')/Folders"
    try:
        r2 = s.get(url2, timeout=30)
        data2 = r2.json()
    except Exception as e:
        print(f"  Skipping subfolders: {folder_path} - {e}")
        return

    for sf in data2["d"]["results"]:
        if sf["Name"] in ("Forms",):
            continue
        download_folder(sf["ServerRelativeUrl"], os.path.join(local_path, sf["Name"]))

# ── Run ───────────────────────────────────────────
for target in SYNC_TARGETS:
    print(f"\nSyncing: {target['remote']}")
    download_folder(target["remote"], target["local"])

print("\nDone.")
