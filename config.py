# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

CHANNEL_USERNAME = os.environ.get(
    "CHANNEL_USERNAME",
    "ScreenEmpire"
).lstrip("@")

DB_CHANNEL = int(
    os.environ.get("DB_CHANNEL", 0)
)

AUTO_DELETE_TIME = int(
    os.environ.get("AUTO_DELETE_TIME", 60)
)

DATABASE_URI = os.environ.get(
    "DATABASE_URI",
    ""
)

# NEW:
# Add your Telegram numeric user ID in Render:
# ADMIN_ID = 123456789
ADMIN_ID = int(
    os.environ.get("ADMIN_ID", 0)
)

# ============================================================
# SEARCH SETTINGS
# ============================================================

RESULTS_PER_PAGE = 5

# Maximum number of matching files kept in one search session.
# This prevents unnecessarily large temporary sessions.
MAX_SEARCH_RESULTS = 100
