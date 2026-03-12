"""LadderBot CLI entry point.

Provides commands for running the daily pipeline, viewing picks,
checking ladder status, backtesting, and launching the web dashboard.
"""
import argparse
import logging
import sys
from datetime import datetime

logger = logging.getLogger("ladderbot")


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser. Separated for testability.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        prog="ladderbot",
        description="LadderBot -- Sports betting parlay optimizer with ladder tracking",
    )

    parser.add_argument(
        "--picks",
        action="store_true",
        help="Show today's picks without sending Discord alert",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Show model performance, ladder state, CLV stats",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Current ladder state + shadow portfolio",
    )
    parser.add_argument(
        "--backtest",
        action="store_true",
        help="Backtest on cached historical data",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force re-fetch all data (ignore cache)",
    )
    parser.add_argument(
        "--sport",
        choices=["nba", "nhl"],
        default=None,
        help="Only run for a specific sport",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Launch web dashboard",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for web dashboard (default: 8000)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config.yaml",
    )

    return parser


def run_pipeline(
    config: dict,
    sport_filter: str | None = None,
    send_alerts: bool = True,
) -> dict:
    """Run the core daily pipeline: fetch -> model -> optimize -> alert.

    This is the main orchestration function. It coordinates all components:
    1. Load data (odds, stats, injuries)
    2. Run models (NBA and/or NHL)
    3. Detect +EV opportunities
    4. Optimize parlays
    5. Update ladder state
    6. Send Discord alerts (if enabled)

    Args:
        config: Validated configuration dict.
        sport_filter: If set, only process this sport ('nba' or 'nhl').
        send_alerts: If True, send Discord alerts. False for --picks mode.

    Returns:
        Dict with pipeline results: picks, parlays, ladder_state, alerts_sent.
    """
    from ladderbot.db.database import get_db
    from ladderbot.parlay.optimizer import find_best_parlays
    from ladderbot.parlay.ladder import LadderTracker, ShadowPortfolio
    from ladderbot.alerts.discord import DiscordAlert

    db = get_db()
    ladder = LadderTracker(db, config)
    shadow = ShadowPortfolio(db)

    # Determine which sports to run
    sports_config = config.get("sports", {})
    sports_to_run = []
    if sport_filter:
        sports_to_run = [sport_filter]
    else:
        if sports_config.get("nba", True):
            sports_to_run.append("nba")
        if sports_config.get("nhl", True):
            sports_to_run.append("nhl")

    # In a full implementation, each sport module would:
    # 1. Fetch today's games and odds
    # 2. Run the prediction model
    # 3. Detect +EV bets via value.py
    # For now, we return the pipeline structure
    ev_bets: list[dict] = []
    # TODO: integrate data layer and models when those modules are built

    # Optimize parlays from +EV candidates
    parlays = find_best_parlays(ev_bets, config)

    result = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "sports": sports_to_run,
        "ev_bets_found": len(ev_bets),
        "parlays": parlays,
        "ladder": ladder.get_ladder_display(),
        "shadow": shadow.get_stats(),
        "alerts_sent": False,
    }

    # Send alerts if we have parlays and alerts are enabled
    if send_alerts and parlays:
        webhook_url = config.get("discord_webhook_url", "")
        if webhook_url:
            alert_client = DiscordAlert(webhook_url)
            top_parlay = parlays[0]
            sent = alert_client.send_pick(
                parlay=top_parlay,
                ladder=result["ladder"],
                shadow=result["shadow"],
            )
            result["alerts_sent"] = sent

    if send_alerts and not parlays:
        webhook_url = config.get("discord_webhook_url", "")
        if webhook_url:
            alert_client = DiscordAlert(webhook_url)
            threshold = config.get("parlay", {}).get("min_edge_per_leg", 0.02)
            alert_client.send_no_picks(
                games_analyzed=0,
                best_edge=0.0,
                threshold=threshold,
            )

    db.close()
    return result


def _print_status(config: dict) -> None:
    """Print current ladder status and shadow portfolio to stdout."""
    from ladderbot.db.database import get_db
    from ladderbot.parlay.ladder import LadderTracker, ShadowPortfolio

    db = get_db()
    ladder = LadderTracker(db, config)
    shadow = ShadowPortfolio(db)

    display = ladder.get_ladder_display()
    stats = shadow.get_stats()

    print("=" * 50)
    print("  LADDERBOT STATUS")
    print("=" * 50)
    print()
    print("LADDER")
    print(f"  Status: {display['status']}")
    print(f"  Step: {display['current_step']} of {display['total_steps']}")
    print(f"  Bankroll: ${display['current_bankroll']:.2f}")
    print(f"  Attempt: #{display['attempt_number']}")
    print()
    print("SHADOW PORTFOLIO")
    print(f"  Record: {stats['wins']}W-{stats['losses']}L")
    print(f"  Profit: ${stats['profit']:+.2f}")
    print(f"  ROI: {stats['roi']:+.1f}%")
    print()

    db.close()


def main():
    """Main entry point for LadderBot CLI."""
    parser = build_parser()
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if args.status:
        try:
            from ladderbot.config import load_config
            config = load_config(args.config) if args.config else load_config()
        except FileNotFoundError:
            from ladderbot.config import DEFAULT_CONFIG
            config = DEFAULT_CONFIG
        _print_status(config)
        return

    if args.web:
        import uvicorn
        from ladderbot.web.app import create_app

        # Load config for the web app
        try:
            from ladderbot.config import load_config
            config = load_config(args.config) if args.config else load_config()
        except FileNotFoundError:
            from ladderbot.config import DEFAULT_CONFIG
            config = DEFAULT_CONFIG

        app = create_app(config)
        print(f"Starting LadderBot web dashboard on port {args.port}...")
        print(f"Open http://localhost:{args.port} in your browser")
        uvicorn.run(app, host="0.0.0.0", port=args.port)
        return

    if args.picks or args.dashboard or args.backtest:
        try:
            from ladderbot.config import load_config
            config = load_config(args.config) if args.config else load_config()
        except FileNotFoundError:
            from ladderbot.config import DEFAULT_CONFIG
            config = DEFAULT_CONFIG

        if args.picks:
            result = run_pipeline(config, sport_filter=args.sport, send_alerts=False)
            if result["parlays"]:
                for i, p in enumerate(result["parlays"], 1):
                    print(f"\nParlay #{i}: {p['parlay_american']:+d}")
                    print(f"  Leg 1: {p['leg1'].get('outcome')} ({p['leg1'].get('odds'):+d})")
                    print(f"  Leg 2: {p['leg2'].get('outcome')} ({p['leg2'].get('odds'):+d})")
                    print(f"  Edge: {p['parlay_edge']*100:.1f}%")
            else:
                print("No +EV parlays found today.")
            return

        if args.dashboard:
            _print_status(config)
            return

        if args.backtest:
            print("Backtest mode: not yet implemented.")
            print("Requires historical odds data in the database.")
            return

    # Default: run the full pipeline
    try:
        from ladderbot.config import load_config
        config = load_config(args.config) if args.config else load_config()
    except FileNotFoundError:
        from ladderbot.config import DEFAULT_CONFIG
        config = DEFAULT_CONFIG
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    result = run_pipeline(config, sport_filter=args.sport, send_alerts=True)
    print(f"Pipeline complete. {len(result['parlays'])} parlays found.")


if __name__ == "__main__":
    main()
