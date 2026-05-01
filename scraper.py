"""
Apify TikTok scraper — three modes:

  profiles  (80% budget) — scrape latest videos from known creator pool
  hashtags  (15% budget) — bootstrap / new-trend discovery
  search    ( 5% budget) — category-specific keyword search
"""

from __future__ import annotations

from apify_client import ApifyClient
from config import APIFY_API_TOKEN, ACTOR_ID


def _client() -> ApifyClient:
    if not APIFY_API_TOKEN:
        raise ValueError("APIFY_API_TOKEN is not set. Copy .env.example to .env and fill it in.")
    return ApifyClient(APIFY_API_TOKEN)


def _run(run_input: dict, label: str) -> list[dict]:
    client = _client()
    print(f"[Apify] Starting '{ACTOR_ID}' — {label}")
    run     = client.actor(ACTOR_ID).call(run_input=run_input)
    dataset = run["defaultDatasetId"]
    items   = list(client.dataset(dataset).iterate_items())
    print(f"[Apify] Done — {len(items)} items from dataset {dataset}")
    return items


# --------------------------------------------------------------------------
# Mode 1: Profiles  (80% budget — main loop)
# --------------------------------------------------------------------------

def scrape_profiles(usernames: list[str], results_per_profile: int = 5) -> list[dict]:
    """
    Fetch the latest `results_per_profile` videos for each creator.
    Most cost-efficient: targets already-validated product creators.
    """
    # Apify processes profiles in batches; split to avoid timeouts on large lists
    BATCH = 100
    all_items: list[dict] = []
    for i in range(0, len(usernames), BATCH):
        batch = usernames[i: i + BATCH]
        items = _run(
            {
                "profiles":              batch,
                "profileScrapeSections": ["videos"],
                "profileSorting":        "latest",
                "resultsPerPage":        results_per_profile,
                "excludePinnedPosts":    True,
                "shouldDownloadVideos":  False,
                "proxyConfiguration":    {"useApifyProxy": True},
            },
            label=f"profiles batch {i//BATCH + 1} ({len(batch)} creators)",
        )
        all_items.extend(items)
    return all_items


# --------------------------------------------------------------------------
# Mode 2: Hashtags  (15% budget — bootstrap + trend discovery)
# --------------------------------------------------------------------------

def scrape_hashtags(hashtags: list[str], results_per_hashtag: int = 10) -> list[dict]:
    """
    Scrape TikTok hashtag feeds.
    High noise — use only for seeding the profile pool or finding new categories.
    """
    return _run(
        {
            "hashtags":           hashtags,
            "resultsPerPage":     results_per_hashtag,
            "excludePinnedPosts": True,
            "shouldDownloadVideos": False,
            "maxRequestRetries":  3,
            "proxyConfiguration": {"useApifyProxy": True},
        },
        label=f"hashtags {hashtags}",
    )


# --------------------------------------------------------------------------
# Mode 3: Search  (5% budget — category keyword supplement)
# --------------------------------------------------------------------------

def scrape_search(queries: list[str], results_per_query: int = 5) -> list[dict]:
    """
    Search TikTok by keyword.
    Useful after locking a category (e.g. "kitchen gadget tiktok shop").
    Results are less stable — use sparingly.
    """
    return _run(
        {
            "searchQueries":      queries,
            "resultsPerPage":     results_per_query,
            "excludePinnedPosts": True,
            "shouldDownloadVideos": False,
            "proxyConfiguration": {"useApifyProxy": True},
        },
        label=f"search {queries}",
    )


# --------------------------------------------------------------------------
# Re-fetch a previous dataset (no API cost)
# --------------------------------------------------------------------------

def fetch_existing_dataset(dataset_id: str) -> list[dict]:
    return list(_client().dataset(dataset_id).iterate_items())
