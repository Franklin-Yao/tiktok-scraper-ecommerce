import os
from dotenv import load_dotenv

load_dotenv()

APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")
ACTOR_ID = "clockworks/tiktok-scraper"

# --------------------------------------------------------------------------
# Scrape mode routing
# --------------------------------------------------------------------------
# If profile pool has fewer than this many profiles, fall back to hashtag bootstrap
PROFILE_POOL_MIN = 20

# --------------------------------------------------------------------------
# Mode 2: Hashtags — bootstrap + daily trend discovery (15% budget)
# --------------------------------------------------------------------------
BOOTSTRAP_HASHTAGS = [
    "TikTokShop",
    "TikTokMadeMeBuyIt",
    "AmazonFinds",
    "TikTokFinds",
    "MustHave",
    "ProductReview",
]
HASHTAG_RESULTS_PER_TAG = 10

# --------------------------------------------------------------------------
# Mode 1: Profiles — main loop (80% budget)
# --------------------------------------------------------------------------
PROFILE_RESULTS_PER_CREATOR = 5   # latest N videos per creator per run
PROFILE_BATCH_SIZE = 100           # creators per Apify call

# --------------------------------------------------------------------------
# Viral score thresholds
# --------------------------------------------------------------------------
MIN_VIEWS = 500_000
MIN_VIEWS_PER_HOUR = 50_000

WEIGHT_VIEWS          = 0.40
WEIGHT_VELOCITY       = 0.30
WEIGHT_ENGAGEMENT_RATE = 0.20
WEIGHT_FRESHNESS      = 0.10

# --------------------------------------------------------------------------
# SKU validation
# --------------------------------------------------------------------------
SKU_VALIDATION_MIN_CREATORS = 3

# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
OUTPUT_DIR = "data"
TOP_N = 20

# --------------------------------------------------------------------------
# Alerts (V1.2)
# --------------------------------------------------------------------------
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")
