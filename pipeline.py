"""
Master pipeline with three-mode routing:

  BOOTSTRAP  — profile pool too small → scrape hashtags, seed the pool
  STEADY     — profile pool ready     → scrape profiles (main loop)
  SUPPLEMENT — daily hashtag top-up   → find new creators / categories

After every run, viral video authors are automatically ingested into
the profile pool (self-growing network).
"""

from __future__ import annotations

from datetime import datetime, timezone

import config
import profile_store
import storage
from scraper import scrape_profiles, scrape_hashtags
from extractor import extract_product_signals, aggregate_sku_validation
from analyzer import score_items, filter_viral, build_action_packs
from reporter import print_action_packs, send_feishu_alert
from profile_manager import ingest_from_videos, record_run_misses, prune_and_report
from comment_signals import fetch_comment_signals, enrich_with_comment_signals


def _mode() -> str:
    pool_size = profile_store.size()
    if pool_size < config.PROFILE_POOL_MIN:
        return "bootstrap"
    return "steady"


def run_pipeline(
    force_mode: str | None = None,   # "bootstrap" | "steady" | "supplement"
    top_n: int | None = None,
    export_csv: bool = True,
    alert: bool = True,
    category: str | None = None,     # filter profiles by category
    fetch_comments: bool = True,     # Method 3: fetch comment purchase intent
) -> list[dict]:

    ts   = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d_%H")
    mode = force_mode or _mode()
    top_n = top_n or config.TOP_N

    print(f"\n[{ts}] Pipeline — mode: {mode.upper()} | pool size: {profile_store.size()}")

    # ------------------------------------------------------------------
    # 1. Scrape
    # ------------------------------------------------------------------
    if mode == "bootstrap":
        print(f"  Bootstrapping from hashtags: {config.BOOTSTRAP_HASHTAGS}")
        raw_items = scrape_hashtags(
            config.BOOTSTRAP_HASHTAGS,
            results_per_hashtag=config.HASHTAG_RESULTS_PER_TAG,
        )
        source = "hashtag_bootstrap"

    elif mode == "supplement":
        print(f"  Supplement hashtag run: {config.BOOTSTRAP_HASHTAGS}")
        raw_items = scrape_hashtags(
            config.BOOTSTRAP_HASHTAGS,
            results_per_hashtag=5,          # smaller quota for supplement
        )
        source = "hashtag_supplement"

    else:  # steady — profile-first
        usernames = profile_store.get_usernames(category=category)
        if not usernames:
            print("  Profile pool empty — falling back to bootstrap.")
            return run_pipeline(force_mode="bootstrap", top_n=top_n,
                                export_csv=export_csv, alert=alert)
        print(f"  Scraping {len(usernames)} profiles (category={category or 'all'})")
        raw_items = scrape_profiles(
            usernames,
            results_per_profile=config.PROFILE_RESULTS_PER_CREATOR,
        )
        source = "profile_steady"

    storage.save_raw(raw_items, ts)
    print(f"  Fetched {len(raw_items)} raw videos.")

    # ------------------------------------------------------------------
    # 2. Extract product signals
    # ------------------------------------------------------------------
    enriched = extract_product_signals(raw_items)
    print(f"  Product videos: {len(enriched)} / {len(raw_items)}")

    # ------------------------------------------------------------------
    # 3. Score + filter
    # ------------------------------------------------------------------
    previous_views = storage.load_previous_views(ts)
    scored = score_items(enriched, previous_views=previous_views)
    viral  = filter_viral(scored)
    print(f"  Viral threshold passed: {len(viral)}")

    # ------------------------------------------------------------------
    # 4. Build action packs
    # ------------------------------------------------------------------
    sku_val = aggregate_sku_validation(enriched)
    packs   = build_action_packs(viral, sku_val)

    # ------------------------------------------------------------------
    # 4b. Method 3 — comment purchase-intent signals (optional, costs API calls)
    # ------------------------------------------------------------------
    if fetch_comments and packs:
        print(f"  Fetching comment signals for top {min(len(packs), 20)} packs...")
        comment_sigs = fetch_comment_signals(viral, max_videos=20)
        packs = enrich_with_comment_signals(packs, comment_sigs)
        intent_count = sum(1 for p in packs if p.get("comment_purchase_intent"))
        print(f"  Comment intent found in {intent_count} videos.")

    # ------------------------------------------------------------------
    # 5. Save + export
    # ------------------------------------------------------------------
    storage.save_action_packs(packs, ts)
    if export_csv:
        csv_path = storage.export_csv(packs, ts)
        print(f"  CSV: {csv_path}")

    # ------------------------------------------------------------------
    # 6. Self-grow profile pool from viral videos
    # ------------------------------------------------------------------
    ingest_result = ingest_from_videos(viral, source=source)
    print(f"  Profile pool — added: {ingest_result['added']}, "
          f"updated: {ingest_result['updated']} | pool size now: {profile_store.size()}")

    # Record misses for profiles that produced nothing this run
    if mode == "steady":
        scraping_usernames = profile_store.get_usernames(category=category)
        viral_usernames    = {(v.get("authorMeta") or {}).get("name", "") for v in viral}
        record_run_misses(scraping_usernames, viral_usernames)

    # Periodic pruning (only in steady mode to avoid removing freshly-added seeds)
    if mode == "steady":
        prune_and_report()

    # ------------------------------------------------------------------
    # 7. Output
    # ------------------------------------------------------------------
    print_action_packs(packs, top_n=top_n)

    if alert:
        send_feishu_alert(packs, top_n=5)

    summary = profile_store.summary()
    print(f"[{ts}] Done — {len(packs)} action packs | "
          f"pool: {summary['total']} profiles across {len(summary['by_category'])} categories\n")

    return packs


def run_supplement() -> list[dict]:
    """Daily hashtag supplement run — finds new creators without replacing steady mode."""
    return run_pipeline(force_mode="supplement", export_csv=False, alert=False)
