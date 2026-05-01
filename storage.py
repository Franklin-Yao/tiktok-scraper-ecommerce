from __future__ import annotations

"""
Persists run results and loads previous run data for velocity calculation.

Each run saves two files under OUTPUT_DIR:
  data/YYYY-MM-DD_HH-raw.json        raw Apify items (for debugging)
  data/YYYY-MM-DD_HH-action_packs.json  final action packs

The previous run's raw items are loaded back to compute views_per_hour.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import config


def _run_timestamp() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d_%H")


def _ensure_output_dir() -> Path:
    path = Path(config.OUTPUT_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_raw(items: list[dict], timestamp: str | None = None) -> Path:
    ts = timestamp or _run_timestamp()
    out = _ensure_output_dir() / f"{ts}-raw.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    return out


def save_action_packs(packs: list[dict], timestamp: str | None = None) -> Path:
    ts = timestamp or _run_timestamp()
    out = _ensure_output_dir() / f"{ts}-action_packs.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(packs, f, ensure_ascii=False, indent=2)
    return out


def load_previous_views(current_timestamp: str | None = None) -> dict[str, int]:
    """
    Find the most recent raw dump (other than the current run) and return a
    {video_id: view_count} mapping for velocity calculation.
    """
    output_dir = _ensure_output_dir()
    raw_files = sorted(output_dir.glob("*-raw.json"), reverse=True)

    current_ts = current_timestamp or _run_timestamp()
    for f in raw_files:
        if current_ts in f.name:
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                items = json.load(fh)
            result = {}
            for item in items:
                if not item.get("id"):
                    continue
                stats = item.get("stats")
                stats = stats if isinstance(stats, dict) else {}
                play_count = item.get("playCount") or stats.get("playCount") or 0
                result[item["id"]] = int(play_count)
            return result
        except Exception:
            continue
    return {}


def export_csv(packs: list[dict], timestamp: str | None = None) -> Path:
    import pandas as pd

    ts = timestamp or _run_timestamp()
    out = _ensure_output_dir() / f"{ts}-action_packs.csv"
    df = pd.DataFrame(packs)
    # flatten list columns
    for col in ("product_links",):
        if col in df.columns:
            df[col] = df[col].apply(lambda v: " | ".join(v) if isinstance(v, list) else v)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    return out
