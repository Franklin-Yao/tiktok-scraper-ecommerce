"""
Persistent profile pool — the core asset of the system.

Stored at data/profiles.json as a dict keyed by author ID.
All mutations go through this module to keep the file consistent.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import config

PROFILES_PATH = Path(config.OUTPUT_DIR) / "profiles.json"

# Category keyword mapping (hashtags / bio text → category)
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "beauty":       ["beauty", "makeup", "skincare", "cosmetic", "haircare", "lipstick", "foundation", "serum"],
    "home_kitchen": ["kitchen", "home", "homedecor", "cleaning", "homeappliance", "cookware", "organiz", "gadget"],
    "fitness":      ["fitness", "workout", "gym", "health", "protein", "supplement", "yoga", "exercise"],
    "pets":         ["pet", "dog", "cat", "puppy", "kitten", "paws", "animal"],
    "gadgets":      ["tech", "gadget", "electronic", "phone", "computer", "device", "smart"],
    "fashion":      ["fashion", "outfit", "clothes", "style", "wear", "dress", "shoes", "accessories"],
    "food":         ["food", "recipe", "cooking", "snack", "drink", "coffee", "kitchen"],
}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _infer_category(hashtags: list[str], bio: str = "") -> str:
    text = " ".join(hashtags).lower() + " " + bio.lower()
    scores: dict[str, int] = {}
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        scores[cat] = sum(1 for kw in keywords if kw in text)
    best = max(scores, key=lambda c: scores[c])
    return best if scores[best] > 0 else "other"


# --------------------------------------------------------------------------
# Load / save
# --------------------------------------------------------------------------

def load() -> dict[str, dict]:
    if not PROFILES_PATH.exists():
        return {}
    with open(PROFILES_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save(pool: dict[str, dict]) -> None:
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROFILES_PATH, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def size() -> int:
    return len(load())


def _calc_commerce_score(p: dict) -> int:
    """
    0–100 score representing how likely this profile is a dedicated seller.
      30  has a shop bio link (shopify/amazon/linktree)
      up to 40  viral_count × 10, capped at 40
      30  collect_ratio signal (set externally)
    """
    score = 0
    if p.get("bio_link"):
        score += 30
    score += min(p.get("viral_count", 0) * 10, 40)
    if p.get("high_collect_ratio"):
        score += 30
    return min(score, 100)


def upsert(author_id: str, username: str, followers: int,
           hashtags: list[str] | None = None,
           bio: str = "",
           bio_link: str = "",
           source: str = "unknown",
           viral: bool = False,
           high_collect_ratio: bool = False) -> dict:
    """
    Add or update a profile in the pool.
    If already present: increments viral_count (if viral=True), updates last_viral_at,
    resets consecutive_misses.
    Returns the updated profile record.
    """
    pool = load()
    now  = _now_iso()

    if author_id in pool:
        p = pool[author_id]
        if viral:
            p["viral_count"]        += 1
            p["last_viral_at"]       = now
            p["consecutive_misses"]  = 0
        p["followers"]  = followers
        if bio_link:
            p["bio_link"] = bio_link
        if username:
            p["username"] = username
        if high_collect_ratio:
            p["high_collect_ratio"] = True
    else:
        category = _infer_category(hashtags or [], bio)
        p = {
            "id":                  author_id,
            "username":            username,
            "followers":           followers,
            "category":            category,
            "viral_count":         1 if viral else 0,
            "last_viral_at":       now if viral else "",
            "bio_link":            bio_link,
            "high_collect_ratio":  high_collect_ratio,
            "added_at":            now,
            "source":              source,
            "consecutive_misses":  0,
        }
        pool[author_id] = p

    p["commerce_score"] = _calc_commerce_score(p)
    _save(pool)
    return p


def record_miss(author_id: str) -> None:
    """Call after a scrape run where this profile produced no viral video."""
    pool = load()
    if author_id in pool:
        pool[author_id]["consecutive_misses"] = pool[author_id].get("consecutive_misses", 0) + 1
        _save(pool)


def prune() -> list[str]:
    """
    Remove stale profiles per deletion rules. Returns list of removed usernames.
    """
    from datetime import timedelta
    pool    = load()
    removed = []
    cutoff  = datetime.now(tz=timezone.utc) - timedelta(days=14)

    to_delete = []
    for aid, p in pool.items():
        # Rule 1: no activity for 14 days
        last_viral = p.get("last_viral_at") or p.get("added_at", "")
        if last_viral:
            try:
                dt = datetime.fromisoformat(last_viral.replace("Z", "+00:00"))
                if dt < cutoff:
                    to_delete.append(aid)
                    removed.append(p["username"])
                    continue
            except ValueError:
                pass
        # Rule 2: too many consecutive misses
        if p.get("consecutive_misses", 0) >= 5:
            to_delete.append(aid)
            removed.append(p["username"])

    for aid in to_delete:
        del pool[aid]

    if to_delete:
        _save(pool)
    return removed


def get_usernames(category: str | None = None, limit: int = 500) -> list[str]:
    """Return list of usernames, optionally filtered by category."""
    pool = load()
    profiles = list(pool.values())
    if category:
        profiles = [p for p in profiles if p.get("category") == category]
    # Prioritise: most viral first, then most recently active
    profiles.sort(key=lambda p: (p.get("commerce_score", 0), p.get("last_viral_at", "")), reverse=True)
    return [p["username"] for p in profiles[:limit]]


def summary() -> dict:
    pool = load()
    by_cat: dict[str, int] = {}
    for p in pool.values():
        cat = p.get("category", "other")
        by_cat[cat] = by_cat.get(cat, 0) + 1
    return {"total": len(pool), "by_category": by_cat}
