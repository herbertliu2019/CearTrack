import os
import time
import requests
import urllib.parse
from datetime import datetime, timezone
from msal import PublicClientApplication, SerializableTokenCache

# ── Configuration ─────────────────────────────────
SITE_URL = "https://cearinc.sharepoint.com/sites/CEARITAD"
FOLDER_PATH = "/sites/CEARITAD/Shared Documents/ITAD Docs/03 Testing/CPU"
LOCAL_DIR = "/mnt/cpu"
CLIENT_ID = "9bc3ab49-b65d-410a-85ad-de819febfddc"
TENANT = "https://login.microsoftonline.com/organizations"
SCOPES = ["https://cearinc.sharepoint.com/.default"]
CACHE_FILE = "/opt/testonedrive/token_cache.bin"

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
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json;odata=verbose"
}

# ── Recursive download ────────────────────────────
#debug  download api
#encoded = urllib.parse.quote(FOLDER_PATH)
#url = f"https://cearinc.sharepoint.com/sites/CEARITAD/_api/web/GetFolderByServerRelativeUrl('{encoded}')?$expand=Files,Folders"
#r = requests.get(url, headers=headers)
#print("Status:", r.status_code)
#print("Response:", r.text[:2000])
def download_folder(folder_path, local_path):
    os.makedirs(local_path, exist_ok=True)

    # Get files
    url = f"https://cearinc.sharepoint.com/sites/CEARITAD/_api/web/GetFolderByServerRelativePath(decodedurl='{folder_path}')/Files?$select=Name,ServerRelativeUrl,TimeLastModified"
    r = requests.get(url, headers=headers)
    if r.status_code != 200 or not r.text:
        print(f"  Skipping (HTTP {r.status_code}): {folder_path}")
        return
    try:
        data = r.json()
    except Exception as e:
        print(f"  Skipping (JSON error): {folder_path} - {e}")
        return

    for f in data["d"]["results"]:
        local_file = os.path.join(local_path, f["Name"])
        # Parse SharePoint modified time
        sp_time_str = f["TimeLastModified"]
        sp_time = datetime.fromisoformat(sp_time_str.replace("Z", "+00:00"))

        # Check if local file exists and is up to date
        if os.path.exists(local_file):
            local_mtime = datetime.fromtimestamp(os.path.getmtime(local_file), tz=timezone.utc)
            if local_mtime >= sp_time:
               # print(f"  Skipping (up to date): {f['Name']}")
                continue

        file_url = f"https://cearinc.sharepoint.com{urllib.parse.quote(f['ServerRelativeUrl'])}"
        print(f"Downloading: {f['ServerRelativeUrl']}")
        resp = requests.get(file_url, headers=headers,stream=True)
        with open(local_file, "wb") as fp:
            for chunk in resp.iter_content(chunk_size=8192):
                fp.write(chunk)
        # Set local file mtime to match SharePoint
        sp_timestamp = sp_time.timestamp()
        os.utime(local_file, (sp_timestamp, sp_timestamp))
        time.sleep(0.3)
    # Get subfolders
    url2 = f"https://cearinc.sharepoint.com/sites/CEARITAD/_api/web/GetFolderByServerRelativePath(decodedurl='{folder_path}')/Folders"
    r2 = requests.get(url2, headers=headers)
    try:
        data2 = r2.json()
    except:
        return

    for sf in data2["d"]["results"]:
        if sf["Name"] in ("Forms",):
            continue
        download_folder(sf["ServerRelativeUrl"], os.path.join(local_path, sf["Name"]))

#-----RUN--------
download_folder(FOLDER_PATH, LOCAL_DIR)
print("\nDone.")
