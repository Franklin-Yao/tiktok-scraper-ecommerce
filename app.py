"""
Flask web dashboard for TikTok Trending Products.

Run:  python app.py
Then open: http://localhost:5000
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from flask import Flask, jsonify, render_template, request

import config
import feedback_store

app = Flask(__name__)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _latest_run() -> tuple[list[dict], str]:
    data_dir = Path(config.OUTPUT_DIR)
    files = sorted(data_dir.glob("*-action_packs.json"), reverse=True)
    if not files:
        return [], "No data yet"
    latest = files[0]
    ts = latest.stem.replace("-action_packs", "")
    with open(latest, encoding="utf-8") as f:
        packs = json.load(f)
    return packs, ts


def _run_summary() -> dict:
    data_dir  = Path(config.OUTPUT_DIR)
    raw_files = sorted(data_dir.glob("*-raw.json"), reverse=True)
    if not raw_files:
        return {"total": 0, "viral": 0}
    with open(raw_files[0], encoding="utf-8") as f:
        raw = json.load(f)
    packs, _ = _latest_run()
    return {"total": len(raw), "viral": len(packs)}


def _enrich_with_model(packs: list[dict]) -> list[dict]:
    """Attach model probability to each pack if a model exists."""
    model = feedback_store.load_model()
    if not model:
        return packs
    for pack in packs:
        features = feedback_store.extract_features(pack)
        pack["model_score"] = round(feedback_store.predict_proba(features), 3)
    return packs


def _labelled_ids() -> set[str]:
    return {l["video_id"] for l in feedback_store.get_labels()}


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.route("/")
def index():
    packs, ts  = _latest_run()
    packs      = _enrich_with_model(packs)
    summary    = _run_summary()
    label_info = feedback_store.label_counts()
    model      = feedback_store.load_model()
    labelled   = _labelled_ids()
    return render_template(
        "dashboard.html",
        packs=packs,
        timestamp=ts,
        summary=summary,
        label_info=label_info,
        model=model,
        labelled=labelled,
    )


@app.route("/api/packs")
def api_packs():
    packs, ts = _latest_run()
    packs     = _enrich_with_model(packs)
    summary   = _run_summary()
    return jsonify({"timestamp": ts, "summary": summary, "packs": packs})


@app.route("/api/label", methods=["POST"])
def api_label():
    """
    Body: { "video_id": "...", "label": 1|0 }
    Looks up the pack from the latest run, extracts features, stores the label.
    """
    data     = request.get_json()
    video_id = data.get("video_id", "")
    label    = int(data.get("label", -1))

    if label not in (0, 1):
        return jsonify({"status": "error", "message": "label must be 0 or 1"}), 400

    packs, _ = _latest_run()
    pack     = next((p for p in packs if p.get("video_id") == video_id), None)
    if not pack:
        return jsonify({"status": "error", "message": "video_id not found"}), 404

    record     = feedback_store.add_label(video_id, label, pack)
    counts     = feedback_store.label_counts()
    model_info = feedback_store.load_model()

    return jsonify({
        "status":      "ok",
        "label":       label,
        "video_id":    video_id,
        "total_labels": counts["total"],
        "model_ready": model_info is not None,
        "model_accuracy": model_info["accuracy"] if model_info else None,
    })


@app.route("/api/train", methods=["POST"])
def api_train():
    """Manually trigger model training."""
    from trainer import train
    result = train()
    return jsonify(result)


@app.route("/api/model")
def api_model():
    model  = feedback_store.load_model()
    counts = feedback_store.label_counts()
    return jsonify({"model": model, "labels": counts})


@app.route("/api/run", methods=["POST"])
def api_run():
    try:
        from pipeline import run_pipeline
        packs = run_pipeline(fetch_comments=False)   # skip comments for speed in web trigger
        return jsonify({"status": "ok", "count": len(packs)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# --------------------------------------------------------------------------
# Daily training job (runs inside the same process)
# --------------------------------------------------------------------------

def _schedule_daily_training() -> None:
    from apscheduler.schedulers.background import BackgroundScheduler
    from trainer import train

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(train, "cron", hour=3, minute=0, id="daily_train")
    scheduler.start()


if __name__ == "__main__":
    _schedule_daily_training()
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, port=port)   # debug=False required with APScheduler
