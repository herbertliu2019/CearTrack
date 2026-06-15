import os
from msal import PublicClientApplication, SerializableTokenCache
from office365.sharepoint.client_context import ClientContext
from office365.runtime.auth.token_response import TokenResponse
import pandas as pd

# ── Configuration ─────────────────────────────────
SITE_URL = "https://cearinc.sharepoint.com/sites/CEARITAD"
FOLDER_PATH = "/sites/CEARITAD/Shared Documents/ITAD Docs/03 Testing/CPU"
LOCAL_DIR = "/mnt/cpu"
CLIENT_ID = "9bc3ab49-b65d-410a-85ad-de819febfddc"
TENANT = "https://login.microsoftonline.com/organizations"
SCOPES = ["https://cearinc.sharepoint.com/.default"]
CACHE_FILE = "/opt/testonedrive/token_cache.bin"

# ── Authentication (with cache) ───────────────────
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

if "access_token" not in result:
    print("Authentication failed:", result.get("error_description"))
    exit(1)

# ── Connect to SharePoint ─────────────────────────
def get_token(scopes=None):
    return TokenResponse(**{
        "token_type": result["token_type"],
        "access_token": result["access_token"]
    })

ctx = ClientContext(SITE_URL).with_access_token(get_token)

# ── Download files ────────────────────────────────
os.makedirs(LOCAL_DIR, exist_ok=True)

folder = ctx.web.get_folder_by_server_relative_url(FOLDER_PATH)
files = folder.files
ctx.load(files)
ctx.execute_query()

print(f"Found {len(files)} files")
for f in files:
    local_path = os.path.join(LOCAL_DIR, f.name)
    print(f"Downloading: {f.name}")
    with open(local_path, "wb") as local_file:
        f.download(local_file).execute_query()

print(f"\nAll files downloaded to {LOCAL_DIR}")

# ── Data analysis ─────────────────────────────────
for filename in os.listdir(LOCAL_DIR):
    filepath = os.path.join(LOCAL_DIR, filename)
    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        print(f"\nAnalyzing: {filename}")
        df = pd.read_excel(filepath)
        print(df.head())
        print(df.describe())
    elif filename.endswith(".csv"):
        print(f"\nAnalyzing: {filename}")
        df = pd.read_csv(filepath)
        print(df.head())
        print(df.describe())
