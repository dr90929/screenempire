import os

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


# ============================================================
# PAID FSub PROMOTIONS
# ============================================================
#
# IMPORTANT:
#
# CHANNEL_USERNAME above is your permanent MAIN channel.
# It is always required.
#
# The two lists below are ONLY for paid/promotional channels.
#
# placement is already separated:
#
# START_FSUB_PROMOTIONS
#     -> Promotion required on /start
#
# SEARCH_FSUB_PROMOTIONS
#     -> Promotion required when searching movies/series
#
# date format:
#     YYYY-MM-DD
#
# enabled:
#     True  = promotion can be active
#     False = promotion disabled manually
#
# Automatic expiry:
#
# Before start_date -> inactive
# Start date to end_date -> active
# After end_date -> automatically inactive
#
# You do NOT need to manually turn it off after the
# end date.
# ============================================================


# ============================================================
# PAID START FSub PROMOTIONS
# ============================================================

START_FSUB_PROMOTIONS = [

    # Example:
    #
    # {
    #     "name": "Client A",
    #     "chat_id": "@ClientChannel",
    #     "url": "https://t.me/ClientChannel",
    #     "start_date": "2026-09-01",
    #     "end_date": "2026-09-10",
    #     "enabled": True
    # }

]


# ============================================================
# PAID SEARCH FSub PROMOTIONS
# ============================================================

SEARCH_FSUB_PROMOTIONS = [

    # Example:
    #
    # {
    #     "name": "Client B",
    #     "chat_id": "@AnotherChannel",
    #     "url": "https://t.me/AnotherChannel",
    #     "start_date": "2026-09-01",
    #     "end_date": "2026-09-15",
    #     "enabled": True
    # }

]
