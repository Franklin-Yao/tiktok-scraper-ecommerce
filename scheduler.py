"""
Hourly daemon mode using APScheduler.
Run with:  python main.py --daemon
"""

from apscheduler.schedulers.blocking import BlockingScheduler

from pipeline import run_pipeline


def start_daemon() -> None:
    scheduler = BlockingScheduler(timezone="UTC")
    # run immediately on start, then every hour
    scheduler.add_job(run_pipeline, "interval", hours=1, id="tiktok_scraper",
                      next_run_time=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    print("Daemon started — running every hour. Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("Daemon stopped.")
