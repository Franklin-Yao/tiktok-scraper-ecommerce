"""
Extracts creators from video data and manages the profile pool.

After every scrape run:
  1. Identify viral videos
  2. Pull author metadata from those videos
  3. Upsert into profile_store (new creators added, existing ones updated)
  4. Record misses for profiles that produced nothing this run
"""

from __future__ import annotations

import re

import config
import profile_store


_SHOP_BIO_RE = re.compile(
    r"shopify|amazon\.com|amzn\.to|linktree|linktr\.ee|ltk\.com|beacons\.ai|stan\.store",
    re.IGNORECASE,
)


def _extract_bio_link(bio: str) -> str:
    """Pull the first shop-like URL from a bio string."""
    urls = re.findall(r"https?://[^\s\)\]\"'<>]+", bio)
    for url in urls:
        if _SHOP_BIO_RE.search(url):
            return url.rstrip(".,;)")
    return ""


def _is_viral(item: dict) -> bool:
    views    = item.get("views") or item.get("playCount") or 0
    velocity = item.get("views_per_hour", 0)
    return int(views) >= config.MIN_VIEWS or int(velocity) >= config.MIN_VIEWS_PER_HOUR


def ingest_from_videos(items: list[dict], source: str = "hashtag_bootstrap") -> dict:
    """
    Process raw (or scored) video items:
    - Upsert authors of viral videos into the profile pool
    - Upsert authors whose bio contains a shop link (strong product signal)

    Returns summary: { added, updated, skipped }
    """
    added = updated = skipped = 0

    for item in items:
        meta      = item.get("authorMeta") or {}
        author_id = meta.get("id") or item.get("authorId", "")
        username  = meta.get("name") or ""
        followers = int(meta.get("fans") or meta.get("followers") or 0)
        bio       = meta.get("signature") or ""
        bio_link  = _extract_bio_link(bio)

        if not author_id or not username:
            skipped += 1
            continue

        viral = _is_viral(item)
        has_shop_bio = bool(bio_link)
        collect_ratio = int(item.get("collectCount") or 0) / max(int(item.get("playCount") or 1), 1)
        high_collect  = collect_ratio >= 0.005

        if not viral and not has_shop_bio and not high_collect:
            skipped += 1
            continue

        hashtags = [(h.get("name") or "").lower() for h in (item.get("hashtags") or [])]

        existing_before = profile_store.size()
        profile_store.upsert(
            author_id=author_id,
            username=username,
            followers=followers,
            hashtags=hashtags,
            bio=bio,
            bio_link=bio_link,
            source=source,
            viral=viral,
            high_collect_ratio=high_collect,
        )
        if profile_store.size() > existing_before:
            added += 1
        else:
            updated += 1

    return {"added": added, "updated": updated, "skipped": skipped}


def record_run_misses(scraped_usernames: list[str], viral_usernames: set[str]) -> None:
    """
    For each profile we scraped that produced no viral video this run,
    increment their consecutive_misses counter.
    """
    pool = profile_store.load()
    username_to_id = {p["username"]: aid for aid, p in pool.items()}

    for username in scraped_usernames:
        if username not in viral_usernames:
            aid = username_to_id.get(username)
            if aid:
                profile_store.record_miss(aid)


def prune_and_report() -> None:
    removed = profile_store.prune()
    if removed:
        print(f"  Pruned {len(removed)} stale profiles: {removed[:5]}{'...' if len(removed) > 5 else ''}")
