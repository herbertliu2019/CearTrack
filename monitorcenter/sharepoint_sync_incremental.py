import os
import sys
import json
import time
import random
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
LAST_SYNC_FILE = "/opt/testonedrive/last_sync.json"
# 全量扫描标志：命令行加 --full 或 -f 触发
FULL_SCAN = "--full" in sys.argv or "-f" in sys.argv
# 增量扫描时间回溯（小时）：避免边界遗漏，每次往前多看 N 小时
INCREMENTAL_OVERLAP_HOURS = 2

SYNC_TARGETS = [
    {
        "remote": "/sites/CEARITAD/Shared Documents/ITAD Docs/06 Testing/CPU",
        "local": "/mnt/CPU",
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

# ── Token 刷新 ────────────────────────────────────
token_lock = threading.Lock()

def get_token():
    """每次获取最新 token，自动刷新（MSAL 会缓存有效 token）"""
    with token_lock:
        accounts = app.get_accounts()
        res = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
        if not res:
            raise RuntimeError("Token 刷新失败，请重新登录")
        if cache.has_state_changed:
            open(CACHE_FILE, "w").write(cache.serialize())
        return res["access_token"]

# ── Thread-local session ──────────────────────────
thread_local = threading.local()

def get_session():
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({
        "Authorization": f"Bearer {get_token()}",
        "Accept": "application/json;odata=verbose",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    return s

# ── Last sync 时间戳 ────────────────────────────────
def load_last_sync(key):
    if not os.path.exists(LAST_SYNC_FILE):
        return None
    try:
        return json.load(open(LAST_SYNC_FILE)).get(key)
    except Exception:
        return None

def save_last_sync(key, iso_timestamp):
    data = {}
    if os.path.exists(LAST_SYNC_FILE):
        try:
            data = json.load(open(LAST_SYNC_FILE))
        except Exception:
            pass
    data[key] = iso_timestamp
    os.makedirs(os.path.dirname(LAST_SYNC_FILE), exist_ok=True)
    json.dump(data, open(LAST_SYNC_FILE, "w"))

# ── Download single file ──────────────────────────
def download_file(server_relative_url, local_file):
    # 用 REST API 的 $value 端点下载，比直链更稳定，避免 Bearer token 在直链下被拒
    p = urllib.parse.quote(server_relative_url, safe="/")
    file_url = f"{BASE_URL}/_api/web/GetFileByServerRelativeUrl(@p1)/$value?@p1='{p}'"
    print(f"Downloading: {server_relative_url}")
    try:
        # 每次下载都获取最新 token
        fresh_token = get_token()
        s = requests.Session()
        retry = Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
        s.mount("https://", HTTPAdapter(max_retries=retry))
        s.headers.update({
            "Authorization": f"Bearer {fresh_token}",
            "Accept": "application/json;odata=verbose",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        resp = s.get(file_url, stream=True, timeout=60)
        if resp.status_code == 401:
            # token 可能刚过期，强制重新获取
            time.sleep(2)
            fresh_token = get_token()
            s.headers.update({"Authorization": f"Bearer {fresh_token}"})
            resp = s.get(file_url, stream=True, timeout=60)
        if resp.status_code == 404:
            # 文件名大小写不匹配，列出目录找实际 .txt 文件
            dir_part = server_relative_url.rsplit("/", 1)[0]
            dir_enc = urllib.parse.quote(dir_part, safe="/")
            folder_api = f"{BASE_URL}/_api/web/GetFolderByServerRelativeUrl(@p1)/Files?@p1='{dir_enc}'&$select=Name,ServerRelativeUrl"
            fr = s.get(folder_api, timeout=30)
            if fr.status_code == 200:
                files = fr.json().get("d", {}).get("results", [])
                txt_files = [f for f in files if f["Name"].lower().endswith(".txt")]
                if txt_files:
                    actual_rel = txt_files[0]["ServerRelativeUrl"]
                    p2 = urllib.parse.quote(actual_rel, safe="/")
                    file_url = f"{BASE_URL}/_api/web/GetFileByServerRelativeUrl(@p1)/$value?@p1='{p2}'"
                    resp = s.get(file_url, stream=True, timeout=60)
                    # 同时更新本地路径文件名与实际文件名一致
                    local_file = os.path.join(os.path.dirname(local_file), txt_files[0]["Name"])
        if resp.status_code != 200:
            print(f"  跳过（HTTP {resp.status_code}）: {server_relative_url}")
            return
        os.makedirs(os.path.dirname(local_file), exist_ok=True)
        with open(local_file, "wb") as fp:
            for chunk in resp.iter_content(chunk_size=65536):
                fp.write(chunk)
        time.sleep(random.uniform(0.3, 1.2))
    except Exception as e:
        print(f"  Failed: {server_relative_url} - {e}")

# ── 用 Search API 列出目标目录下所有文件 ─────────────
def list_remote_files(list_title, folder_path, since_iso=None):
    """返回 [(server_relative_url, time_last_modified), ...]
    since_iso: ISO 时间戳，只返回该时间之后修改的文件
    """
    s = get_session()
    results = []
    folder_path = folder_path.rstrip("/")

    # Search API：path: 限定根目录，IsDocument:1 只要文件
    folder_url = f"https://cearinc.sharepoint.com{folder_path}"
    query = f'path:"{folder_url}" IsDocument:1'
    if since_iso:
        # Write 是 SharePoint 索引中的修改时间字段
        query += f' Write>={since_iso}'
        print(f"  增量模式：只取 {since_iso} 之后修改的文件")
    row_limit = 500
    start = 0

    while True:
        params = {
            "querytext": f"'{query}'",
            "selectproperties": "'Path,LastModifiedTime,IsDocument'",
            "rowlimit": str(row_limit),
            "startrow": str(start),
            "trimduplicates": "false",
        }
        # 翻页前刷新 token
        s.headers.update({"Authorization": f"Bearer {get_token()}"})
        r = s.get(f"{BASE_URL}/_api/search/query", params=params, timeout=60)
        if r.status_code != 200:
            print(f"  [ERROR] Search API {r.status_code}: {r.text[:300]}")
            break

        primary = r.json()["d"]["query"]["PrimaryQueryResult"]
        hits = primary["RelevantResults"]
        total = hits["TotalRows"]
        rows = hits["Table"]["Rows"]["results"]

        seen = {r[0] for r in results}
        for row in rows:
            cells = {c["Key"]: c["Value"] for c in row["Cells"]["results"]}
            path = cells.get("Path", "")
            mtime = cells.get("LastModifiedTime", "")
            # 统一 decode，消除 %20 与空格混用导致的重复
            server_rel = urllib.parse.unquote(path.replace("https://cearinc.sharepoint.com", ""))
            if server_rel and server_rel not in seen:
                seen.add(server_rel)
                results.append((server_rel, mtime))

        print(f"  已找到 {len(results)} / {total} 个文件")
        start += len(rows)
        if start >= total or not rows:
            break
        time.sleep(random.uniform(1.5, 3.0))  # 翻页间隔，模拟人工浏览

    return results

# ── 同步单个目标 ──────────────────────────────────
def sync_target(list_title, remote_base, local_base):
    remote_base = remote_base.rstrip("/")
    key = remote_base

    # 决定本次扫描时间窗口
    since_iso = None
    if not FULL_SCAN:
        last = load_last_sync(key)
        if last:
            since_dt = datetime.fromisoformat(last.replace("Z", "+00:00")) - timedelta(hours=INCREMENTAL_OVERLAP_HOURS)
            since_iso = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 记录本次开始时间（成功完成后保存）
    run_start = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"  正在列出远程文件...")
    remote_files = list_remote_files(list_title, remote_base, since_iso=since_iso)

    seen = set()
    to_download = []
    for server_url, _ in remote_files:
        if not server_url.lower().endswith(".txt"):
            continue
        if server_url in seen:
            print(f"  [SKIP重复] {server_url}")
            continue
        seen.add(server_url)
        relative = server_url[len(remote_base):]
        local_file = local_base + relative
        to_download.append((server_url, local_file))

    print(f"  去重后共 {len(to_download)} 个文件，开始下载覆盖...")

    for url, lf in to_download:
        download_file(url, lf)

    # 同步完成后记录本次时间戳，下次从这个时间开始增量
    save_last_sync(key, run_start)
    print(f"  下次增量起点：{run_start}")

# ── Run ───────────────────────────────────────────
print(f"模式: {'全量扫描' if FULL_SCAN else '增量扫描'}")
for target in SYNC_TARGETS:
    print(f"\nSyncing: {target['remote']}")
    sync_target(target["list"], target["remote"], target["local"])

print("\nDone.")
