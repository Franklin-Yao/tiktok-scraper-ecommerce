from __future__ import annotations

"""
Renders Action Packs to the terminal and sends optional Feishu alerts.
"""

import json
import os
from pathlib import Path

import requests
from tabulate import tabulate

import config


def _fmt_num(n) -> str:
    if n is None:
        return "-"
    n = int(n)
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.0f}K"
    return str(n)


def _stars(n: int) -> str:
    return "⭐" * n + "☆" * (5 - n)


def print_action_packs(packs: list[dict], top_n: int | None = None) -> None:
    top = packs[: top_n or config.TOP_N]
    if not top:
        print("No viral shoppable videos found in this run.")
        return

    print(f"\n{'='*80}")
    print(f"  🔥  TikTok Trending Product Report  —  Top {len(top)} Action Packs")
    print(f"{'='*80}\n")

    table_rows = []
    for rank, p in enumerate(top, 1):
        validated = "✅" if p.get("sku_validated") else "—"
        table_rows.append([
            rank,
            _fmt_num(p.get("views")),
            f"+{_fmt_num(p.get('views_per_hour'))}/h",
            f"{p.get('viral_score', 0):.3f}",
            p.get("creator_handle", "")[:20],
            _fmt_num(p.get("creator_fans")),
            f"{p.get('creator_count', 1)} creators {validated}",
            _stars(p.get("replica_difficulty_stars", 3)),
            p.get("priority", "")[:40],
        ])

    headers = ["#", "Views", "Velocity", "Score", "Creator", "Fans",
               "SKU Validation", "Difficulty", "Priority"]
    print(tabulate(table_rows, headers=headers, tablefmt="rounded_outline"))

    print("\n--- Action Pack Details ---\n")
    for rank, p in enumerate(top, 1):
        print(f"[#{rank}]  Score: {p.get('viral_score', 0):.3f}  |  "
              f"Views: {_fmt_num(p.get('views'))}  |  "
              f"Velocity: +{_fmt_num(p.get('views_per_hour'))}/h  |  "
              f"{p.get('hours_old')}h old")
        print(f"  Creator : @{p.get('creator_handle')}  ({_fmt_num(p.get('creator_fans'))} fans)")
        print(f"  Video   : {p.get('video_url') or p.get('video_id')}")
        print(f"  Desc    : {(p.get('description') or '')[:120]}")
        print(f"  Product : {p.get('product_name') or '(unknown)'}")
        print(f"  Shop at : {p.get('sample_product_link') or '(check creator bio)'}")
        print(f"  SKU Val : {p.get('creator_count', 1)} creator(s) — "
              f"{'VALIDATED ✅' if p.get('sku_validated') else 'not yet validated'}")
        print(f"  Replica : {_stars(p.get('replica_difficulty_stars', 3))}  "
              f"{p.get('replica_difficulty_label', '')}")
        print(f"  Priority: {p.get('priority', '')}")
        print()


def send_feishu_alert(packs: list[dict], top_n: int = 5) -> None:
    """Post top action packs to a Feishu webhook (V1.2 feature)."""
    if not config.FEISHU_WEBHOOK_URL:
        return

    top = packs[:top_n]
    lines = ["**🔥 TikTok Trending Products Alert**\n"]
    for rank, p in enumerate(top, 1):
        lines.append(
            f"**#{rank}** @{p.get('creator_handle')} — "
            f"{_fmt_num(p.get('views'))} views (+{_fmt_num(p.get('views_per_hour'))}/h)\n"
            f"Product: {p.get('sample_product_link', 'N/A')}\n"
            f"Priority: {p.get('priority', '')}\n"
        )

    payload = {"msg_type": "text", "content": {"text": "\n".join(lines)}}
    try:
        resp = requests.post(config.FEISHU_WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        print(f"Feishu alert sent ({len(top)} packs).")
    except Exception as e:
        print(f"Feishu alert failed: {e}")
