"""
Public REST API — deploy on zeus.rocks

Run dev:   python api.py
Run prod:  gunicorn api:app -w 4 -b 0.0.0.0:8000

Endpoints:
  GET  /v1/trending            top trending products (last 24h)
  GET  /v1/trending/<video_id> single product detail
  GET  /v1/pool                profile pool stats
  GET  /v1/health              health check
  POST /v1/scrape              trigger a fresh scrape run
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request
from flask_cors import CORS

import config
import profile_store

app = Flask(__name__)
CORS(app)  # allow all origins — public API


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _latest_packs() -> tuple[list[dict], str]:
    files = sorted(Path(config.OUTPUT_DIR).glob("*-action_packs.json"), reverse=True)
    if not files:
        return [], ""
    ts = files[0].stem.replace("-action_packs", "")
    with open(files[0], encoding="utf-8") as f:
        return json.load(f), ts


def _fmt_num(n) -> str:
    if n is None:
        return "0"
    n = int(n)
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(n)


def _pack_to_response(p: dict, detail: bool = False) -> dict:
    """Serialise an action pack to a clean API response dict."""
    base = {
        "video_id":       p.get("video_id"),
        "video_url":      p.get("video_url"),
        "cover_url":      p.get("cover_url"),
        "published_at":   p.get("published_at"),
        "hours_old":      p.get("hours_old"),

        "metrics": {
            "views":          p.get("views"),
            "views_fmt":      _fmt_num(p.get("views")),
            "views_per_hour": p.get("views_per_hour"),
            "velocity_fmt":   f"+{_fmt_num(p.get('views_per_hour'))}/h",
            "likes":          p.get("likes"),
            "comments":       p.get("comments"),
            "shares":         p.get("shares"),
            "viral_score":    p.get("viral_score"),
            "collect_ratio":  p.get("collect_ratio"),
        },

        "product": {
            "name":         p.get("product_name"),
            "signals":      p.get("signals", []),
            "shop_link":    (p.get("shop_links") or {}).get("bio_link"),
            "amazon_url":   (p.get("shop_links") or {}).get("amazon_search"),
            "tiktok_shop_url": (p.get("shop_links") or {}).get("tiktok_shop"),
            "sku_validated": p.get("sku_validated", False),
            "creator_count": p.get("creator_count", 1),
        },

        "creator": {
            "handle":     p.get("creator_handle"),
            "fans":       p.get("creator_fans"),
            "fans_fmt":   _fmt_num(p.get("creator_fans")),
            "profile_url": (p.get("shop_links") or {}).get("creator_profile"),
        },

        "action": {
            "priority":               p.get("priority"),
            "replica_difficulty":     p.get("replica_difficulty_stars"),
            "replica_difficulty_label": p.get("replica_difficulty_label"),
        },
    }

    if detail:
        base["description"]       = p.get("description")
        base["comment_signals"]   = p.get("comment_signals")
        base["comment_purchase_intent"] = p.get("comment_purchase_intent")
        base["model_score"]       = p.get("model_score")

    return base


def _error(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.route("/v1/health")
def health():
    packs, ts = _latest_packs()
    return jsonify({
        "status":       "ok",
        "last_run":     ts,
        "pack_count":   len(packs),
        "profile_pool": profile_store.size(),
        "server_time":  datetime.now(tz=timezone.utc).isoformat(),
    })


@app.route("/v1/trending")
def trending():
    """
    Query params:
      limit     int   max results (default 20, max 100)
      category  str   filter by category (beauty, home_kitchen, gadgets, ...)
      min_views int   minimum view count filter
      hours     int   only videos published within last N hours (default 24)
    """
    limit     = min(int(request.args.get("limit", 20)), 100)
    category  = request.args.get("category", "").lower() or None
    min_views = int(request.args.get("min_views", 0))
    hours     = float(request.args.get("hours", 24))

    packs, ts = _latest_packs()
    if not packs:
        return jsonify({"data": [], "meta": {"total": 0, "last_run": ts}})

    # Filter
    filtered = [
        p for p in packs
        if (p.get("views") or 0) >= min_views
        and (p.get("hours_old") or 9999) <= hours
    ]

    if category:
        # Match on product signals or creator category
        filtered = [p for p in filtered if category in " ".join(p.get("signals", [])).lower()
                    or category in (p.get("product_name") or "").lower()]

    results = [_pack_to_response(p) for p in filtered[:limit]]

    return jsonify({
        "data": results,
        "meta": {
            "total":        len(results),
            "last_run":     ts,
            "filters_applied": {
                "hours":     hours,
                "min_views": min_views,
                "category":  category,
                "limit":     limit,
            },
        },
    })


@app.route("/v1/trending/<video_id>")
def trending_detail(video_id: str):
    packs, ts = _latest_packs()
    pack = next((p for p in packs if p.get("video_id") == video_id), None)
    if not pack:
        return _error(f"video_id '{video_id}' not found in latest run", 404)
    return jsonify({"data": _pack_to_response(pack, detail=True), "meta": {"last_run": ts}})


@app.route("/v1/pool")
def pool():
    summary = profile_store.summary()
    usernames = profile_store.get_usernames(limit=10)  # top 10 by commerce_score
    return jsonify({
        "total":       summary["total"],
        "by_category": summary["by_category"],
        "top_creators": usernames,
    })


@app.route("/v1/scrape", methods=["POST"])
def scrape():
    """Trigger a fresh scrape. Returns immediately with job_id = timestamp."""
    import threading
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d_%H%M")

    def _run():
        from pipeline import run_pipeline
        run_pipeline(fetch_comments=False)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return jsonify({
        "status":  "started",
        "job_id":  ts,
        "message": "Scrape started in background. Poll /v1/health to see when last_run updates.",
    }), 202


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
