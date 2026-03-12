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


def _extract_bookmaker_odds(event: dict, bookmaker_key: str | None) -> dict | None:
    """Extract h2h and totals odds from an Odds API event for a given bookmaker.

    Args:
        event: Raw event dict from The Odds API.
        bookmaker_key: Bookmaker key (e.g. "draftkings") or None for first available.

    Returns:
        Dict with home_ml, away_ml, total_line, over_odds, under_odds, or None.
    """
    for bk in event.get("bookmakers", []):
        if bookmaker_key is not None and bk.get("key") != bookmaker_key:
            continue

        result = {}
        for market in bk.get("markets", []):
            mkey = market.get("key", "")
            outcomes = market.get("outcomes", [])

            if mkey == "h2h":
                home_team = event.get("home_team", "")
                for o in outcomes:
                    if o.get("name") == home_team:
                        result["home_ml"] = o.get("price")
                    else:
                        result["away_ml"] = o.get("price")

            elif mkey == "totals":
                for o in outcomes:
                    if o.get("name") == "Over":
                        result["over_odds"] = o.get("price")
                        result["total_line"] = o.get("point")
                    elif o.get("name") == "Under":
                        result["under_odds"] = o.get("price")

        if result.get("home_ml") is not None:
            return result

    return None


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
    from ladderbot.db.database import get_db, insert_pick, insert_parlay
    from ladderbot.data.odds import OddsClient, OddsClientError
    from ladderbot.models.value import find_ev_bets
    from ladderbot.parlay.optimizer import find_best_parlays
    from ladderbot.parlay.ladder import LadderTracker, ShadowPortfolio
    from ladderbot.alerts.discord import DiscordAlert
    from ladderbot.utils.odds import implied_probability

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

    # Sport keys for The Odds API
    sport_keys = {
        "nba": "basketball_nba",
        "nhl": "icehockey_nhl",
    }

    # --- Step 1: Fetch odds and build game/prediction data ---
    odds_client = OddsClient(config.get("odds_api_key", ""), db)
    all_games = []
    all_odds_data = {}
    all_predictions = {}
    games_analyzed = 0

    for sport in sports_to_run:
        sport_key = sport_keys.get(sport)
        if not sport_key:
            continue

        try:
            events = odds_client.get_odds(sport_key, markets="h2h,totals")
        except OddsClientError as exc:
            logger.warning("Failed to fetch %s odds: %s", sport, exc)
            continue

        for event in events:
            game_id = event.get("id", "")
            home = event.get("home_team", "")
            away = event.get("away_team", "")

            all_games.append({
                "game_id": game_id,
                "sport": sport,
                "home": home,
                "away": away,
            })

            # Extract DraftKings odds (preferred) or first available bookmaker
            dk_odds = _extract_bookmaker_odds(event, "draftkings")
            if dk_odds is None:
                dk_odds = _extract_bookmaker_odds(event, None)  # first available
            if dk_odds is None:
                continue

            all_odds_data[game_id] = dk_odds

            # Generate predictions using implied probabilities as baseline
            # (Models need training data to beat this — this uses line-shopping edge only)
            home_implied = implied_probability(dk_odds["home_ml"]) if dk_odds.get("home_ml") else 0.5
            away_implied = implied_probability(dk_odds["away_ml"]) if dk_odds.get("away_ml") else 0.5

            # Slight home-court/ice advantage adjustment (+1.5% for NBA, +1% for NHL)
            home_adj = 0.015 if sport == "nba" else 0.01
            home_prob = min(home_implied + home_adj, 0.95)

            pred = {"home_win_prob": home_prob}

            # Totals: use the line as predicted total (no edge until model trained)
            if dk_odds.get("total_line"):
                pred["predicted_total"] = dk_odds["total_line"]

            all_predictions[game_id] = pred
            games_analyzed += 1

    # --- Step 2: Detect +EV bets ---
    ev_bets = find_ev_bets(
        all_games, all_predictions, all_odds_data, config.get("parlay", {})
    )
    logger.info("Found %d +EV bets across %d games", len(ev_bets), games_analyzed)

    # Normalize ev_bets keys for optimizer (it expects 'odds', value.py outputs 'book_odds')
    for bet in ev_bets:
        bet["odds"] = bet.get("book_odds", bet.get("odds", 0))

    # --- Step 3: Optimize parlays ---
    parlays = find_best_parlays(ev_bets, config)

    # --- Step 4: Store picks and parlays in DB (skip duplicates) ---
    today = datetime.now().strftime("%Y-%m-%d")
    existing = db.execute(
        """SELECT p.combined_odds, pk1.game_id as g1, pk2.game_id as g2
           FROM parlays p
           LEFT JOIN picks pk1 ON p.leg1_pick_id = pk1.pick_id
           LEFT JOIN picks pk2 ON p.leg2_pick_id = pk2.pick_id
           WHERE date(p.created_at) = ?""",
        (today,),
    ).fetchall()
    existing_keys = {(r["g1"], r["g2"], r["combined_odds"]) for r in existing}

    for parlay in parlays:
        leg1 = parlay["leg1"]
        leg2 = parlay["leg2"]

        # Skip if same game pair + odds already stored today
        key = (leg1["game_id"], leg2["game_id"], parlay["parlay_american"])
        if key in existing_keys:
            logger.debug("Skipping duplicate parlay: %s", key)
            continue

        pick1_id = insert_pick(
            db, leg1["game_id"], leg1.get("market", "h2h"),
            leg1.get("team", leg1.get("outcome", "")), leg1["odds"],
        )
        pick2_id = insert_pick(
            db, leg2["game_id"], leg2.get("market", "h2h"),
            leg2.get("team", leg2.get("outcome", "")), leg2["odds"],
        )
        parlay_id = insert_parlay(
            db, pick1_id, pick2_id,
            parlay["parlay_american"], parlay["parlay_edge"],
        )
        parlay["parlay_id"] = parlay_id

        # Record shadow flat bets
        shadow.record_bet(pick1_id, leg1["odds"])
        shadow.record_bet(pick2_id, leg2["odds"])

    result = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "sports": sports_to_run,
        "games_analyzed": games_analyzed,
        "ev_bets_found": len(ev_bets),
        "parlays": parlays,
        "ladder": ladder.get_ladder_display(),
        "shadow": shadow.get_stats(),
        "alerts_sent": False,
    }

    # Send alerts if we have parlays and alerts are enabled
    webhook_url = config.get("discord_webhook_url", "")
    if send_alerts and webhook_url:
        alert_client = DiscordAlert(webhook_url)
        if parlays:
            top_parlay = parlays[0]
            sent = alert_client.send_pick(
                parlay=top_parlay,
                ladder=result["ladder"],
                shadow=result["shadow"],
            )
            result["alerts_sent"] = sent
        else:
            best_edge = max((b["edge"] for b in ev_bets), default=0.0)
            threshold = config.get("parlay", {}).get("min_edge_per_leg", 0.02)
            alert_client.send_no_picks(
                games_analyzed=games_analyzed,
                best_edge=best_edge,
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
            print(f"\nAnalyzed {result['games_analyzed']} games, found {result['ev_bets_found']} +EV bets")
            if result["parlays"]:
                for i, p in enumerate(result["parlays"], 1):
                    leg1, leg2 = p["leg1"], p["leg2"]
                    print(f"\n{'='*50}")
                    print(f"  PARLAY #{i}: {p['parlay_american']:+d} (Edge: {p['parlay_edge']*100:.1f}%)")
                    print(f"{'='*50}")
                    print(f"  Leg 1: {leg1.get('team', leg1.get('outcome'))} "
                          f"({leg1.get('sport','').upper()} {leg1.get('market','ML')}) "
                          f"{leg1['odds']:+d}")
                    print(f"         Model: {leg1['model_prob']*100:.1f}% | "
                          f"Book: {leg1['book_implied_prob']*100:.1f}% | "
                          f"Edge: {leg1['edge']*100:.1f}%")
                    print(f"  Leg 2: {leg2.get('team', leg2.get('outcome'))} "
                          f"({leg2.get('sport','').upper()} {leg2.get('market','ML')}) "
                          f"{leg2['odds']:+d}")
                    print(f"         Model: {leg2['model_prob']*100:.1f}% | "
                          f"Book: {leg2['book_implied_prob']*100:.1f}% | "
                          f"Edge: {leg2['edge']*100:.1f}%")
                    print(f"  Combined: {p['combined_prob']*100:.1f}% prob × "
                          f"{p['parlay_decimal']:.2f}x = {p['parlay_edge']*100:+.1f}% EV")
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
