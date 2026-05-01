"""
Entry point.

Usage:
  python main.py                          # auto-route (bootstrap or steady)
  python main.py --mode bootstrap         # force hashtag bootstrap
  python main.py --mode steady            # force profile scrape
  python main.py --mode supplement        # daily hashtag top-up
  python main.py --category home_kitchen  # steady, filter to one category
  python main.py --top 30
  python main.py --pool                   # show profile pool summary
  python main.py --daemon                 # hourly loop
"""

import argparse

import profile_store


def main() -> None:
    parser = argparse.ArgumentParser(
        description="TikTok Trending Product Scraper — Executable Selection Engine"
    )
    parser.add_argument("--mode",     choices=["bootstrap", "steady", "supplement"],
                        help="Force a specific scrape mode (default: auto)")
    parser.add_argument("--category", help="Filter profile pool by category")
    parser.add_argument("--top",      type=int, help="Number of action packs to display")
    parser.add_argument("--no-csv",   action="store_true", help="Skip CSV export")
    parser.add_argument("--no-alert", action="store_true", help="Skip Feishu alert")
    parser.add_argument("--pool",     action="store_true", help="Print profile pool summary and exit")
    parser.add_argument("--daemon",   action="store_true", help="Run as hourly daemon")
    args = parser.parse_args()

    if args.pool:
        summary = profile_store.summary()
        print(f"Profile pool: {summary['total']} creators")
        for cat, count in sorted(summary["by_category"].items(), key=lambda x: -x[1]):
            print(f"  {cat:<20} {count}")
        return

    if args.daemon:
        from scheduler import start_daemon
        start_daemon()
    else:
        from pipeline import run_pipeline
        run_pipeline(
            force_mode=args.mode,
            top_n=args.top,
            export_csv=not args.no_csv,
            alert=not args.no_alert,
            category=args.category,
        )


if __name__ == "__main__":
    main()
