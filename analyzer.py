"""
Scores enriched video items and assembles Action Packs.

Viral Score formula (weights defined in config.py):
  score = w_views   * norm(views)
        + w_velocity * norm(views_per_hour)
        + w_engagement * engagement_rate        # already 0-1
        + w_freshness  * freshness_score        # 0-1, decays after 24 h

An Action Pack is a dict that bundles content signal + product signal +
replica difficulty into one ready-to-use record.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

import config
from extractor import aggregate_sku_validation


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _get_stats(item: dict) -> tuple[int, int, int, int]:
    """Return (views, likes, comments, shares) for a video item."""
    stats = item.get("stats") or {}
    # Apify TikTok scraper may nest stats or flatten them
    stats = stats if isinstance(stats, dict) else {}
    views    = _safe_int(item.get("playCount")    or stats.get("playCount"))
    likes    = _safe_int(item.get("diggCount")    or stats.get("diggCount"))
    comments = _safe_int(item.get("commentCount") or stats.get("commentCount"))
    shares   = _safe_int(item.get("shareCount")   or stats.get("shareCount"))
    return views, likes, comments, shares


def _published_at(item: dict) -> Optional[datetime]:
    ts = item.get("createTime") or item.get("createTimeISO")
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _hours_since(dt: Optional[datetime]) -> float:
    if dt is None:
        return 24.0
    delta = datetime.now(tz=timezone.utc) - dt
    return max(delta.total_seconds() / 3600, 0.0)


def _freshness_score(hours_old: float) -> float:
    """1.0 at 0 h, decays to 0 at 48 h (linear)."""
    return max(0.0, 1.0 - hours_old / 48.0)


def _engagement_rate(views: int, likes: int, comments: int, shares: int) -> float:
    if views == 0:
        return 0.0
    return min((likes + comments * 2 + shares * 3) / views, 1.0)


def _log_norm(value: float, scale: float) -> float:
    """Log-normalise a value against a reference scale (e.g. 5M views)."""
    if value <= 0:
        return 0.0
    return min(math.log1p(value) / math.log1p(scale), 1.0)


def _replica_difficulty(item: dict, views: int) -> tuple[int, str]:
    """
    Return (star_count 1-5, label) estimating how hard it is to replicate.
    Heuristic: small accounts + high views = easy viral format.
    """
    follower_count = _safe_int(
        (item.get("authorMeta") or {}).get("fans")
        or (item.get("authorMeta") or {}).get("followers")
    )
    # large creator with many followers → harder to replicate their reach
    if follower_count > 1_000_000:
        stars, label = 4, "Hard — mega creator, needs strong following"
    elif follower_count > 100_000:
        stars, label = 3, "Medium — mid-tier creator"
    elif follower_count > 10_000:
        stars, label = 2, "Easy — small creator, replicable format"
    else:
        stars, label = 1, "Very Easy — micro creator, low production bar"
    return stars, label


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def score_items(
    items: list[dict],
    previous_views: dict[str, int] | None = None,
    hours_between_runs: float = 1.0,
) -> list[dict]:
    """
    Add a `viral_score` and velocity fields to each item.

    previous_views: {video_id: view_count} from the last run — used to
    compute views_per_hour.  Pass None to skip velocity scoring.
    """
    previous_views = previous_views or {}

    VIEW_SCALE = 5_000_000   # normalisation reference for raw views
    VEL_SCALE  = 500_000     # normalisation reference for views/h

    scored = []
    for item in items:
        views, likes, comments, shares = _get_stats(item)
        vid_id = item.get("id", "")

        # velocity
        prev = previous_views.get(vid_id)
        if prev is not None and hours_between_runs > 0:
            views_per_hour = max((views - prev) / hours_between_runs, 0.0)
        else:
            hours_old = _hours_since(_published_at(item))
            views_per_hour = views / max(hours_old, 1.0)

        # component scores
        s_views      = _log_norm(views, VIEW_SCALE)
        s_velocity   = _log_norm(views_per_hour, VEL_SCALE)
        s_engagement = _engagement_rate(views, likes, comments, shares)
        hours_old    = _hours_since(_published_at(item))
        s_freshness  = _freshness_score(hours_old)

        viral_score = (
            config.WEIGHT_VIEWS          * s_views
            + config.WEIGHT_VELOCITY     * s_velocity
            + config.WEIGHT_ENGAGEMENT_RATE * s_engagement
            + config.WEIGHT_FRESHNESS    * s_freshness
        )

        item = dict(item)
        item["views"]          = views
        item["likes"]          = likes
        item["comments"]       = comments
        item["shares"]         = shares
        item["views_per_hour"] = round(views_per_hour)
        item["hours_old"]      = round(hours_old, 1)
        item["viral_score"]    = round(viral_score, 4)
        scored.append(item)

    return scored


def filter_viral(items: list[dict]) -> list[dict]:
    """Keep only items that meet at least one viral threshold."""
    return [
        i for i in items
        if i.get("views", 0) >= config.MIN_VIEWS
        or i.get("views_per_hour", 0) >= config.MIN_VIEWS_PER_HOUR
    ]


def build_action_packs(
    items: list[dict],
    sku_validation: dict[str, dict],
) -> list[dict]:
    """
    Combine scored video items with SKU validation data into Action Packs,
    sorted by views descending.
    """
    # Deduplicate by video_id — same video can appear via multiple hashtags
    seen: set[str] = set()
    unique_items = []
    for item in sorted(items, key=lambda x: x.get("views", 0), reverse=True):
        vid = item.get("id", "")
        if vid and vid in seen:
            continue
        seen.add(vid)
        unique_items.append(item)

    packs = []
    for item in unique_items:
        author_meta   = item.get("authorMeta") or {}
        author_handle = author_meta.get("name") or author_meta.get("nickName") or "unknown"
        author_fans   = _safe_int(author_meta.get("fans") or author_meta.get("followers"))

        product_links = item.get("product_links", [])
        sku_keys      = item.get("sku_keys", [])

        # find strongest SKU validation for this video
        best_sku = max(
            (sku_validation.get(k, {}) for k in sku_keys),
            key=lambda v: v.get("creator_count", 0),
            default={},
        )
        creator_count = best_sku.get("creator_count", 1)
        validated     = creator_count >= config.SKU_VALIDATION_MIN_CREATORS

        diff_stars, diff_label = _replica_difficulty(item, item.get("views", 0))

        # priority label
        if item.get("views_per_hour", 0) >= config.MIN_VIEWS_PER_HOUR and validated:
            priority = "HIGH — still exploding + product validated"
        elif item.get("views_per_hour", 0) >= config.MIN_VIEWS_PER_HOUR:
            priority = "MEDIUM — still exploding, limited product validation"
        elif validated:
            priority = "MEDIUM — product validated but velocity slowing"
        else:
            priority = "LOW — monitor only"

        pack = {
            # content signal
            "video_id":        item.get("id", ""),
            "video_url":       item.get("webVideoUrl") or item.get("videoUrl") or "",
            "cover_url":       (item.get("videoMeta") or {}).get("coverUrl") or "",
            "published_at":    item.get("createTimeISO") or str(item.get("createTime", "")),
            "hours_old":       item.get("hours_old"),
            "views":           item.get("views"),
            "views_per_hour":  item.get("views_per_hour"),
            "likes":           item.get("likes"),
            "comments":        item.get("comments"),
            "shares":          item.get("shares"),
            "viral_score":     item.get("viral_score"),
            "description":     (item.get("text") or item.get("desc") or "")[:200],
            # product signal
            "product_name":       item.get("product_name", ""),
            "shop_links":         item.get("shop_links", {}),
            "has_direct_link":    item.get("has_direct_link", False),
            "product_links":      product_links[:3],
            "sku_validated":      validated,
            "creator_count":      creator_count,
            "sample_product_link": best_sku.get("sample_link", product_links[0] if product_links else ""),
            # creator info
            "creator_handle":  author_handle,
            "creator_fans":    author_fans,
            # action guidance
            "replica_difficulty_stars": diff_stars,
            "replica_difficulty_label": diff_label,
            "priority":        priority,
        }
        packs.append(pack)

    return packs
