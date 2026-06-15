import os
import json
import threading
import requests
import urllib.parse
from datetime import datetime, timezone, timedelta
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
CHANGE_TOKEN_FILE = "/opt/testonedrive/change_token.json"

SYNC_TARGETS = [
    {
        "remote": "/sites/CEARITAD/Shared Documents/ITAD Docs/03 Testing/CPU",
        "local": "/mnt/CPU",
        "list": "Documents"
    },
    {
        "remote": "/sites/CEARITAD/Shared Documents/ITAD Docs/04 Data Wiping/EPS/logs",
        "local": "/mnt/WIPE",
        "list": "Documents"
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

# ── Load/save change token ────────────────────────
def load_change_token(key):
    if os.path.exists(CHANGE_TOKEN_FILE):
        data = json.load(open(CHANGE_TOKEN_FILE))
        return data.get(key)
    return None

def save_change_token(key, token_value):
    data = {}
    if os.path.exists(CHANGE_TOKEN_FILE):
        data = json.load(open(CHANGE_TOKEN_FILE))
    data[key] = token_value
    json.dump(data, open(CHANGE_TOKEN_FILE, "w"))

# ── Download single file ──────────────────────────
def download_file(server_relative_url, local_file):
    file_url = f"https://cearinc.sharepoint.com{urllib.parse.quote(server_relative_url)}"
    print(f"Downloading: {server_relative_url}")
    try:
        s = get_session()
        resp = s.get(file_url, stream=True, timeout=60)
        os.makedirs(os.path.dirname(local_file), exist_ok=True)
        with open(local_file, "wb") as fp:
            for chunk in resp.iter_content(chunk_size=65536):
                fp.write(chunk)
    except Exception as e:
        print(f"  Failed: {server_relative_url} - {e}")

# ── Get changes since last run ────────────────────
def get_changes(list_title, remote_base, local_base, change_token=None):
    s = get_session()
    since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    url = f"{BASE_URL}/_api/web/lists/getbytitle('{list_title}')/items?$filter=Modified gt datetime'{since}'&$select=FileRef,Modified,FSObjType&$top=5000"

    r = s.get(url, timeout=30)
    if r.status_code != 200:
        print(f"  API error: {r.status_code}")
        return None, None

    data = r.json()
    items = data["d"]["results"]

    # 只处理目标路径下的文件（FSObjType=0）
    filtered = [
        item for item in items
        if item["FSObjType"] == 0 and item["FileRef"].startswith(remote_base)
    ]
    print(f"  Found {len(filtered)} changed files in {remote_base}")

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for item in filtered:
            file_ref = item["FileRef"]
            relative = file_ref[len(remote_base):]
            local_file = local_base + relative
            futures.append(executor.submit(download_file, file_ref, local_file))
        for future in as_completed(futures):
            future.result()

    return None, None

    # 获取最新 change token
    new_token = changes[-1]["ChangeToken"]["StringValue"] if changes else change_token

    # 处理变更
    futures = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        for change in changes:
            change_type = change.get("ChangeType")  # 1=Add, 2=Update, 3=Delete
            server_url = change.get("ServerRelativeUrl", "")

            # 只处理目标目录下的文件
            if not server_url.startswith(remote_base):
                continue

            relative = server_url[len(remote_base):]
            local_file = local_base + relative

            if change_type in (1, 2):  # Add or Update
                futures.append(executor.submit(download_file, server_url, local_file))
            elif change_type == 3:  # Delete
                if os.path.exists(local_file):
                    os.remove(local_file)
                    print(f"Deleted: {local_file}")

        for future in as_completed(futures):
            future.result()

    return new_token, change_token

# ── Run ───────────────────────────────────────────
for target in SYNC_TARGETS:
    key = target["remote"]
    print(f"\nSyncing: {key}")
    old_token = load_change_token(key)
    new_token, _ = get_changes(target["list"], target["remote"], target["local"], old_token)
    if new_token:
        save_change_token(key, new_token)

print("\nDone.")
