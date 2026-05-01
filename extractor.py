"""
Identifies shoppable/commercial videos and extracts product signals.

A video is considered a "product video" only if it passes at least one
HARD SIGNAL — either an explicit purchase CTA in the description text, or
a specific ecommerce hashtag.  isAd / isSponsored alone is not enough
because TikTok marks promoted entertainment content as ads too.

SKU-level deduplication uses a normalised product keyword extracted from
the video description so the same product mentioned by multiple creators
counts as multi-creator validation.
"""

from __future__ import annotations

import re
from collections import defaultdict

# --------------------------------------------------------------------------
# Signal definitions
# --------------------------------------------------------------------------

# HARD SIGNAL 1: explicit purchase / shop CTA in description text
_BUY_CTA = re.compile(
    r"link in (my )?bio"
    r"|shop (at|now|my|the link)"
    r"|buy (now|it|this|here|one|yours)"
    r"|get yours"
    r"|order (now|here|yours)"
    r"|available (at|now|on|in)"
    r"|grab yours"
    r"|linked below"
    r"|check.*link"
    r"|find.*link"
    r"|\$\s?[1-9]\d+"     # price ≥ $10 only — avoids street food "$ 0.17"
    r"|use code\b"        # discount code
    r"|promo code"
    r"|coupon"
    r"|affiliate",
    re.IGNORECASE,
)

# HARD SIGNAL 2: specific ecommerce hashtags (NOT generic viral/trending)
_ECOMMERCE_HASHTAGS = {
    "amazonfinds", "tiktokmademebuyit", "tiktokshop", "amazondeals",
    "amazongadgets", "amazonmusthaves", "amazonproducts", "amazonhomefinds",
    "amazonbeauty", "amazonfavorites", "amazonfinds2026", "tiktokfinds",
    "musthave", "productreview", "founditonamazon", "shopwithme",
    "haul", "unboxing", "gadgets", "kitchengadgets", "homefinds",
    "beautyfinds", "techtok", "cleaningtok", "tiktokshopcreatorpicks",
    "dealdrop", "amazonhome", "lifehack", "lifehacks", "amazonkitchen",
    "amazonskincare", "amazontech", "amazonpets", "amazonbaby",
}

# SOFT SIGNAL 3: high save/collect ratio relative to views
# Entertainment videos: likes >> saves. Product videos: saves are higher (bookmark to buy).
# Threshold: collectCount / playCount > 0.5%
_COLLECT_RATIO_THRESHOLD = 0.005

# Hashtags that indicate non-product content regardless of other signals
# SOFT SIGNAL: author bio points to a shopping storefront
# (only counted when combined with at least one other indicator)
_SHOP_BIO = re.compile(
    r"link in bio|all products|shop my|storefront|amazon\.com/shop"
    r"|ltk\.com|linktree|linktr\.ee|beacons\.ai|stan\.store",
    re.IGNORECASE,
)


def _collect_ratio(item: dict) -> float:
    plays   = int(item.get("playCount") or 0)
    saves   = int(item.get("collectCount") or 0)
    return saves / plays if plays > 0 else 0.0


def _hard_signals(item: dict) -> list[str]:
    """Return list of signal names present in this item (empty = not a product video)."""
    found = []

    # Method 1: explicit buy CTA in caption
    text = (item.get("text") or "") + " " + (item.get("desc") or "")
    if _BUY_CTA.search(text):
        found.append("buy_cta")

    # Method 2: specific ecommerce hashtag
    hashtags = {(h.get("name") or "").lower() for h in (item.get("hashtags") or [])}
    if hashtags & _ECOMMERCE_HASHTAGS:
        found.append("ecommerce_hashtag")

    # Method 4: high save/collect ratio (bookmarked to buy later)
    if _collect_ratio(item) >= _COLLECT_RATIO_THRESHOLD:
        found.append("high_collect_ratio")

    return found


# Hashtags that indicate non-product content regardless of other signals
_ENTERTAINMENT_HASHTAGS = {
    "streetfood", "food", "foodie", "travel", "vlog", "comedy",
    "funny", "prank", "dance", "music", "art", "nature", "animals",
    "fitness", "workout", "motivation", "news", "politics",
}

def _is_product_video(item: dict) -> bool:
    """
    A video qualifies if:
    - It has at least one HARD signal (buy_cta or ecommerce_hashtag), OR
    - It has high_collect_ratio PLUS at least one other signal (collect alone
      isn't strong enough — dance/music videos also get saved)
    AND it doesn't look like pure entertainment content.
    """
    signals = _hard_signals(item)
    if not signals:
        return False

    # collect_ratio alone: require at least one supporting signal
    if signals == ["high_collect_ratio"]:
        return False

    # Reject if all hashtags are pure entertainment
    hashtags = {(h.get("name") or "").lower() for h in (item.get("hashtags") or [])}
    if hashtags and hashtags.issubset(_ENTERTAINMENT_HASHTAGS | {"viral", "trending", "fyp", "foryou", "shorts"}):
        return False

    return True


# --------------------------------------------------------------------------
# Product name extraction
# --------------------------------------------------------------------------

# Words too generic to be a product name
_STOPWORDS = {
    "the", "this", "that", "these", "those", "just", "really", "very",
    "actually", "best", "amazing", "viral", "trending", "finds", "find",
    "products", "product", "review", "amazon", "tiktok", "shop", "buy",
    "link", "bio", "check", "out", "new", "good", "great", "love",
    "must", "have", "need", "want", "get", "got", "use", "used",
}


def _extract_product_name(item: dict) -> str:
    """
    Extract a meaningful product name from the video description.

    Priority:
      1. Explicit buy CTA with product noun: "Buy Portable Dishwasher"
      2. Description noun phrase describing a physical object
      3. Specific vertical ecommerce hashtag (e.g. "kitchengadgets")
      4. First clean sentence from description
    """
    text = (item.get("text") or "").strip()
    # Text before any hashtags (the human-written description)
    desc = re.split(r"#|\n", text)[0].strip()

    # 1. Explicit buy/shop CTA followed by product name
    m = re.search(
        r"(?:buy|get|order|shop|grab)\s+([A-Za-z0-9][^#@]{3,50}?)(?=\s*[#@\n]|$)",
        text, re.IGNORECASE,
    )
    if m:
        name = m.group(1).strip(" .,!?\n")
        if len(name) > 3 and name.lower() not in _STOPWORDS:
            return name[:60]

    # 2. Noun phrase in description — look for "the X that/which/is" patterns
    #    e.g. "The clownfish that starts swimming" → "clownfish"
    #    e.g. "Smart Toothbrush Holder Disinfector"
    m = re.search(
        r"(?:the\s+)?([A-Z][a-z]+(?:\s+[A-Za-z]+){0,4})\s+(?:that|which|is|are|has|with|for)\b",
        desc,
    )
    if m:
        candidate = m.group(1).strip()
        words = candidate.lower().split()
        if not all(w in _STOPWORDS for w in words):
            return candidate[:60]

    # 3. Title-cased product phrase in description (e.g. "Portable Dishwasher", "Mini Blender")
    m = re.search(
        r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){0,3})\b",
        desc,
    )
    if m:
        candidate = m.group(1).strip()
        if candidate.lower() not in _STOPWORDS and len(candidate) > 4:
            return candidate[:60]

    # 4. Specific vertical ecommerce hashtag (not generic ones)
    _generic = {"amazonfinds", "tiktokmademebuyit", "tiktokshop", "musthave",
                "productreview", "viral", "trending", "fyp", "foryou",
                "foryoupage", "shorts", "tiktok"}
    hashtags = [(h.get("name") or "").lower() for h in (item.get("hashtags") or [])]
    for tag in hashtags:
        if tag in _ECOMMERCE_HASHTAGS and tag not in _generic:
            return tag

    # 5. First non-empty meaningful word sequence from desc
    clean = re.sub(r"[^\w\s]", " ", desc).strip()
    words = [w for w in clean.split() if w.lower() not in _STOPWORDS and len(w) > 2]
    if words:
        return " ".join(words[:4])

    return desc[:50]


def _extract_shop_links(item: dict) -> dict:
    """
    Return a dict of available shopping destinations for this video:
      bio_link       – direct URL found in author's bio (most valuable)
      amazon_search  – Amazon search URL for the product name
      tiktok_shop    – TikTok Shop search URL for the product name
      creator_profile – TikTok profile (fallback, user clicks "link in bio" manually)
    """
    links: dict[str, str] = {}

    # 1. Direct URL in author bio (highest value — actual storefront)
    bio = (item.get("authorMeta") or {}).get("signature", "") or ""
    bio_urls = re.findall(r"https?://[^\s\)\]\"'<>]+", bio)
    # Filter out social/video platform links — keep only shop/commerce URLs
    shop_url_re = re.compile(
        r"(shopify|amazon\.com|amzn\.to|ltk\.com|linktree|linktr\.ee|"
        r"beacons\.ai|stan\.store|etsy\.com|shop\.|myshop|store\.)",
        re.IGNORECASE,
    )
    for url in bio_urls:
        if shop_url_re.search(url):
            links["bio_link"] = url.rstrip(".,;)")
            break

    # 2. Amazon search URL from product name
    product_name = _extract_product_name(item)
    if product_name:
        query = re.sub(r"[^\w\s]", "", product_name).strip()
        if query:
            links["amazon_search"] = (
                f"https://www.amazon.com/s?k={query.replace(' ', '+')}&tag=tiktok-trending"
            )
            links["tiktok_shop"] = (
                f"https://www.tiktok.com/search?q={query.replace(' ', '%20')}&type=product"
            )

    # 3. Creator profile (fallback)
    meta = item.get("authorMeta") or {}
    profile = meta.get("profileUrl") or ""
    if not profile:
        name = meta.get("name") or ""
        profile = f"https://www.tiktok.com/@{name}" if name else ""
    links["creator_profile"] = profile

    return links


def _best_shop_link(links: dict) -> str:
    """Return the most valuable shopping link available."""
    return links.get("bio_link") or links.get("tiktok_shop") or links.get("creator_profile", "")


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def extract_product_signals(items: list[dict]) -> list[dict]:
    """
    Filter to product videos (hard signal required) and enrich with:
      - signals: list of matched signal names
      - product_name: extracted product keyword
      - product_links: [creator profile URL]
      - sku_keys: [normalised product name for cross-video dedup]
    """
    enriched = []
    for item in items:
        signals = _hard_signals(item)
        if not signals:
            continue
        item = dict(item)
        product_name = _extract_product_name(item)
        shop_links   = _extract_shop_links(item)
        item["signals"]          = signals
        item["is_commercial"]    = True
        item["product_name"]     = product_name
        item["shop_links"]       = shop_links
        item["product_links"]    = [_best_shop_link(shop_links)]
        item["sku_keys"]         = [product_name.lower()] if product_name else []
        item["has_direct_link"]  = "bio_link" in shop_links
        item["collect_ratio"]    = round(_collect_ratio(item), 4)
        enriched.append(item)
    return enriched


def aggregate_sku_validation(items: list[dict]) -> dict[str, dict]:
    """
    For each product name, count distinct creators and collect video IDs.
    Returns: { product_name: { creator_count, video_ids, sample_link } }
    """
    sku_creators: dict[str, set]  = defaultdict(set)
    sku_videos:   dict[str, list] = defaultdict(list)
    sku_sample:   dict[str, str]  = {}

    for item in items:
        author_id = (item.get("authorMeta") or {}).get("id") or "unknown"
        video_id  = item.get("id", "")
        for sku_key in item.get("sku_keys", []):
            sku_creators[sku_key].add(author_id)
            sku_videos[sku_key].append(video_id)
            if sku_key not in sku_sample:
                links = item.get("product_links", [])
                sku_sample[sku_key] = links[0] if links else ""

    return {
        sku: {
            "creator_count": len(sku_creators[sku]),
            "video_ids":     sku_videos[sku],
            "sample_link":   sku_sample.get(sku, ""),
        }
        for sku in sku_creators
    }
