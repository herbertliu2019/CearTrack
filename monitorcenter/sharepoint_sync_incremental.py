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
# 需要下载的文件扩展名：txt（CPU 测试结果）+ 图片（截图，供详情卡展示/下载）
DOWNLOAD_EXTS = (".txt", ".png", ".jpg", ".jpeg")

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
            # 文件名大小写不匹配，列出目录找同扩展名的实际文件
            want_ext = os.path.splitext(server_relative_url)[1].lower()
            dir_part = server_relative_url.rsplit("/", 1)[0]
            dir_enc = urllib.parse.quote(dir_part, safe="/")
            folder_api = f"{BASE_URL}/_api/web/GetFolderByServerRelativeUrl(@p1)/Files?@p1='{dir_enc}'&$select=Name,ServerRelativeUrl"
            fr = s.get(folder_api, timeout=30)
            if fr.status_code == 200:
                files = fr.json().get("d", {}).get("results", [])
                match_files = [f for f in files if f["Name"].lower().endswith(want_ext)]
                if match_files:
                    actual_rel = match_files[0]["ServerRelativeUrl"]
                    p2 = urllib.parse.quote(actual_rel, safe="/")
                    file_url = f"{BASE_URL}/_api/web/GetFileByServerRelativeUrl(@p1)/$value?@p1='{p2}'"
                    resp = s.get(file_url, stream=True, timeout=60)
                    # 同时更新本地路径文件名与实际文件名一致
                    local_file = os.path.join(os.path.dirname(local_file), match_files[0]["Name"])
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

def _get_with_throttle_log(s, url, label):
    """GET 并打印限流/重试可见的详细信息，避免长时间无输出看起来像卡死。"""
    t0 = time.time()
    try:
        r = s.get(url, timeout=60)
    except Exception as e:
        print(f"    [EXC] {label}: {e} ({time.time()-t0:.1f}s)")
        raise
    elapsed = time.time() - t0
    if r.status_code == 429:
        retry_after = r.headers.get("Retry-After", "?")
        print(f"    [429 限流] {label} Retry-After={retry_after}s 耗时={elapsed:.1f}s")
    elif elapsed > 5:
        print(f"    [慢请求 {elapsed:.1f}s] {label}")
    return r


# 剪枝起始深度：只对第 PRUNE_FROM_DEPTH 层及更深的子目录按 mtime 剪枝。
# 目录结构 CPU(0) / By SN(1) / <SN>(2) / files —— SN 目录在深度 2，是文件所在的叶子层。
# SharePoint 加文件只更新“直接父目录”的 mtime，不冒泡到爷爷目录，
# 所以中间容器（CPU、By SN）不能按自身 mtime 剪枝（否则会漏掉旧 SN 目录里的新文件），
# 只对叶子层 SN 目录剪枝才安全。深度 0/1 始终进入，深度 >=2 才按 mtime 判断。
PRUNE_FROM_DEPTH = 2


# ── 用 REST 文件夹接口递归列出文件（叶子目录按 mtime 剪枝，跳过未变更的旧目录） ─
def _list_folder_recursive(s, folder_rel, results, since_iso, depth=0):
    """递归枚举 folder_rel 下所有文件，append (server_relative_url, mtime) 到 results。
    不依赖搜索索引 → png/jpg 不会被漏；增量模式对叶子目录按 mtime 剪枝，跳过旧目录。
    """
    enc = urllib.parse.quote(folder_rel, safe="/")

    # 1) 本层文件
    files_api = (f"{BASE_URL}/_api/web/GetFolderByServerRelativeUrl(@p1)/Files"
                 f"?@p1='{enc}'&$select=Name,ServerRelativeUrl,TimeLastModified&$top=5000")
    s.headers.update({"Authorization": f"Bearer {get_token()}"})
    r = _get_with_throttle_log(s, files_api, f"Files @ {folder_rel}")
    if r.status_code != 200:
        print(f"  [ERROR] Files API {r.status_code} @ {folder_rel}: {r.text[:200]}")
    else:
        for f in r.json().get("d", {}).get("results", []):
            server_rel = urllib.parse.unquote(f["ServerRelativeUrl"])
            mtime = f.get("TimeLastModified", "")
            # 增量：即使进入了目录，仍按文件 mtime 二次过滤（防边界内混有旧文件）
            if since_iso and mtime and mtime < since_iso:
                continue
            results.append((server_rel, mtime))

    # 2) 子目录：列出（带 mtime），增量时对叶子层按 mtime 剪枝
    folders_api = (f"{BASE_URL}/_api/web/GetFolderByServerRelativeUrl(@p1)/Folders"
                   f"?@p1='{enc}'&$select=Name,ServerRelativeUrl,TimeLastModified&$top=5000")
    s.headers.update({"Authorization": f"Bearer {get_token()}"})
    r = _get_with_throttle_log(s, folders_api, f"Folders @ {folder_rel}")
    if r.status_code != 200:
        print(f"  [ERROR] Folders API {r.status_code} @ {folder_rel}: {r.text[:200]}")
        return

    all_subs = [sub for sub in r.json().get("d", {}).get("results", [])
                if sub.get("Name") != "Forms" and not sub.get("Name", "").startswith("_")]

    child_depth = depth + 1
    skipped = 0
    subs = []
    for sub in all_subs:
        sub_mtime = sub.get("TimeLastModified", "")
        # 只对 PRUNE_FROM_DEPTH 层及更深的目录剪枝，中间容器始终进入
        if (since_iso and child_depth >= PRUNE_FROM_DEPTH
                and sub_mtime and sub_mtime < since_iso):
            skipped += 1
            continue
        subs.append(sub)

    print(f"  [目录] {folder_rel} → {len(all_subs)} 个子目录，"
          f"进入 {len(subs)}，跳过 {skipped}（累计文件 {len(results)}）")

    for sub in subs:
        sub_rel = urllib.parse.unquote(sub["ServerRelativeUrl"])
        time.sleep(random.uniform(0.3, 0.8))  # 目录间隔，降低被限流概率
        _list_folder_recursive(s, sub_rel, results, since_iso, depth=child_depth)


def list_remote_files(list_title, folder_path, since_iso=None):
    """返回 [(server_relative_url, time_last_modified), ...]
    since_iso: ISO 时间戳，只返回该时间之后修改的文件
    """
    s = get_session()
    results = []
    folder_path = folder_path.rstrip("/")

    if since_iso:
        print(f"  增量模式：跳过 mtime < {since_iso} 的叶子目录（深度 >= {PRUNE_FROM_DEPTH}）")

    _list_folder_recursive(s, folder_path, results, since_iso)

    # 去重（同一 URL 只保留一次）
    dedup = {}
    for server_rel, mtime in results:
        if server_rel not in dedup:
            dedup[server_rel] = mtime
    print(f"  已找到 {len(dedup)} 个文件")
    return list(dedup.items())

    # 去重（同一 URL 只保留一次）
    dedup = {}
    for server_rel, mtime in results:
        if server_rel not in dedup:
            dedup[server_rel] = mtime
    print(f"  已找到 {len(dedup)} 个文件")
    return list(dedup.items())

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
        if not server_url.lower().endswith(DOWNLOAD_EXTS):
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
