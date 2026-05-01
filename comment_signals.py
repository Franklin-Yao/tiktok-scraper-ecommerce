"""
Method 3: Comment purchase-intent detection.

For viral videos that have a commentsDatasetUrl, we fetch the top comments
and look for purchase-intent phrases ("where to buy", "link?", "how much",
"I need this", etc.).

This runs AFTER the initial viral filter to avoid paying API cost for
every video — only called for confirmed viral product videos.
"""

from __future__ import annotations

import re
from apify_client import ApifyClient
from config import APIFY_API_TOKEN

_PURCHASE_INTENT = re.compile(
    r"where (can i |do i )?buy|where to (get|find|buy|order)"
    r"|link\?|link please|drop the link|send (me )?the link"
    r"|how much|what'?s? the (price|cost)"
    r"|i need this|need this|i want this|want this"
    r"|where is this from|where did you get"
    r"|can i order|how (do i|to) order"
    r"|is this on amazon|amazon link"
    r"|shop\?|where to shop",
    re.IGNORECASE,
)


def _dataset_id_from_url(url: str) -> str | None:
    """Extract Apify dataset ID from a commentsDatasetUrl."""
    m = re.search(r"datasets/([a-zA-Z0-9]+)", url or "")
    return m.group(1) if m else None


def fetch_comment_signals(items: list[dict], max_videos: int = 20) -> dict[str, dict]:
    """
    For up to `max_videos` viral items that have a commentsDatasetUrl,
    fetch their comments and return purchase-intent signals.

    Returns: { video_id: { intent_count, intent_ratio, sample_comments } }
    """
    if not APIFY_API_TOKEN:
        return {}

    client = ApifyClient(APIFY_API_TOKEN)
    results: dict[str, dict] = {}

    candidates = [
        i for i in items
        if i.get("commentsDatasetUrl") and i.get("id")
    ][:max_videos]

    for item in candidates:
        video_id  = item["id"]
        url       = item["commentsDatasetUrl"]
        dataset_id = _dataset_id_from_url(url)
        if not dataset_id:
            continue

        try:
            comments = list(client.dataset(dataset_id).iterate_items(limit=20))
        except Exception:
            continue

        intent_comments = []
        for c in comments:
            text = c.get("text") or c.get("comment") or ""
            if _PURCHASE_INTENT.search(text):
                intent_comments.append(text[:100])

        total = len(comments)
        intent_count = len(intent_comments)
        results[video_id] = {
            "intent_count":    intent_count,
            "intent_ratio":    round(intent_count / total, 2) if total > 0 else 0,
            "sample_comments": intent_comments[:3],
            "comments_total":  total,
        }

    return results


def enrich_with_comment_signals(packs: list[dict], comment_signals: dict[str, dict]) -> list[dict]:
    """Merge comment signal data into action packs."""
    for pack in packs:
        vid = pack.get("video_id", "")
        if vid in comment_signals:
            pack["comment_signals"] = comment_signals[vid]
            # Boost priority label if strong comment intent
            sig = comment_signals[vid]
            if sig["intent_count"] >= 3 or sig["intent_ratio"] >= 0.2:
                pack["comment_purchase_intent"] = True
                if "LOW" in pack.get("priority", ""):
                    pack["priority"] = pack["priority"].replace("LOW", "MEDIUM") + " + comment intent ✅"
        else:
            pack["comment_purchase_intent"] = False
    return packs
