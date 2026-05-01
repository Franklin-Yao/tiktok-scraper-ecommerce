"""
Stores user labels (👍 带货 / 👎 非带货) and extracts feature vectors
used to train the self-improving classifier.

Label file: data/labels.json
Model file: data/model.json
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import config

LABELS_PATH = Path(config.OUTPUT_DIR) / "labels.json"
MODEL_PATH  = Path(config.OUTPUT_DIR) / "model.json"

# Feature names — must stay in this order for the model
FEATURE_NAMES = [
    "collect_ratio",
    "has_buy_cta",
    "has_ecommerce_hashtag",
    "has_high_collect_ratio",
    "engagement_rate",
    "views_per_hour_log",
    "hours_old_norm",
    "has_bio_link",
    "followers_log",
    "is_ad",
]


def extract_features(pack: dict) -> dict:
    """
    Extract a fixed feature vector from an action pack dict.
    All values are floats in roughly [0, 1].
    """
    signals = pack.get("signals") or []
    views   = max(pack.get("views") or 0, 1)
    likes   = pack.get("likes") or 0
    comments = pack.get("comments") or 0
    shares  = pack.get("shares") or 0

    engagement = (likes + comments * 2 + shares * 3) / views

    shop_links = pack.get("shop_links") or {}

    return {
        "collect_ratio":           float(pack.get("collect_ratio") or 0),
        "has_buy_cta":             1.0 if "buy_cta" in signals else 0.0,
        "has_ecommerce_hashtag":   1.0 if "ecommerce_hashtag" in signals else 0.0,
        "has_high_collect_ratio":  1.0 if "high_collect_ratio" in signals else 0.0,
        "engagement_rate":         min(float(engagement), 1.0),
        "views_per_hour_log":      math.log1p(pack.get("views_per_hour") or 0) / math.log1p(500_000),
        "hours_old_norm":          min(float(pack.get("hours_old") or 24) / 48.0, 1.0),
        "has_bio_link":            1.0 if shop_links.get("bio_link") else 0.0,
        "followers_log":           math.log1p(pack.get("creator_fans") or 0) / math.log1p(10_000_000),
        "is_ad":                   1.0 if pack.get("is_ad") else 0.0,
    }


def feature_vector(features: dict) -> list[float]:
    return [features[k] for k in FEATURE_NAMES]


# --------------------------------------------------------------------------
# Label store
# --------------------------------------------------------------------------

def _load_labels() -> list[dict]:
    if not LABELS_PATH.exists():
        return []
    with open(LABELS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_labels(labels: list[dict]) -> None:
    LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LABELS_PATH, "w", encoding="utf-8") as f:
        json.dump(labels, f, ensure_ascii=False, indent=2)


def add_label(video_id: str, label: int, pack: dict) -> dict:
    """
    Store a user label.
    label = 1 (带货) or 0 (非带货)
    Returns the saved record.
    """
    labels = _load_labels()

    # Overwrite if already labelled
    labels = [l for l in labels if l["video_id"] != video_id]

    features = extract_features(pack)
    record   = {
        "video_id":   video_id,
        "label":      label,
        "features":   features,
        "video_url":  pack.get("video_url", ""),
        "creator":    pack.get("creator_handle", ""),
        "product":    pack.get("product_name", ""),
        "labelled_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    labels.append(record)
    _save_labels(labels)
    return record


def get_labels() -> list[dict]:
    return _load_labels()


def label_counts() -> dict:
    labels = _load_labels()
    pos = sum(1 for l in labels if l["label"] == 1)
    neg = len(labels) - pos
    return {"total": len(labels), "positive": pos, "negative": neg}


# --------------------------------------------------------------------------
# Model store
# --------------------------------------------------------------------------

def save_model(weights: list[float], intercept: float,
               accuracy: float, trained_on: int) -> None:
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "feature_names": FEATURE_NAMES,
            "weights":       weights,
            "intercept":     intercept,
            "accuracy":      accuracy,
            "trained_on":    trained_on,
            "trained_at":    datetime.now(tz=timezone.utc).isoformat(),
        }, f, indent=2)


def load_model() -> dict | None:
    if not MODEL_PATH.exists():
        return None
    with open(MODEL_PATH, encoding="utf-8") as f:
        return json.load(f)


def predict_proba(features: dict) -> float:
    """
    Return P(带货) using the saved logistic regression model.
    Returns -1.0 if no model is available yet.
    """
    model = load_model()
    if not model:
        return -1.0
    import math
    vec = feature_vector(features)
    w   = model["weights"]
    b   = model["intercept"]
    z   = sum(wi * xi for wi, xi in zip(w, vec)) + b
    return 1.0 / (1.0 + math.exp(-z))
