"""Discord embed formatter for LadderBot.

Formats pick alerts, result notifications, and daily summaries
as Discord webhook-compatible embed dicts.
"""
from ladderbot.utils.odds import classify_confidence


def format_pick_embed(
    parlay: dict,
    ladder: dict,
    shadow: dict,
) -> dict:
    """Format a pick alert as a Discord embed.

    Args:
        parlay: Parlay dict with leg1, leg2, parlay_american, parlay_edge, etc.
        ladder: Ladder display dict with status, current_step, total_steps,
                current_bankroll, attempt_number.
        shadow: Shadow portfolio stats dict with wins, losses, profit, roi.

    Returns:
        Discord embed dict ready for webhook payload.
    """
    leg1 = parlay.get("leg1", {})
    leg2 = parlay.get("leg2", {})

    step = ladder.get("current_step", 1)
    total = ladder.get("total_steps", 4)
    bankroll = ladder.get("current_bankroll", 10.0)
    attempt = ladder.get("attempt_number", 1)

    leg1_conf = classify_confidence(leg1.get("edge", 0))
    leg2_conf = classify_confidence(leg2.get("edge", 0))

    parlay_american = parlay.get("parlay_american", 0)
    parlay_edge = parlay.get("parlay_edge", 0)
    parlay_decimal = parlay.get("parlay_decimal", 1.0)

    potential_win = bankroll * parlay_decimal
    next_step_val = potential_win

    # Shadow stats
    sw = shadow.get("wins", 0)
    sl = shadow.get("losses", 0)
    sp = shadow.get("profit", 0.0)
    sr = shadow.get("roi", 0.0)

    description_lines = [
        f"**Current Bankroll:** ${bankroll:.2f} | **Betting:** ${bankroll:.2f}",
        "",
        f"**LEG 1:** {leg1.get('outcome', '?')} {leg1.get('market', '')} "
        f"({leg1.get('odds', 0):+d}) | Edge: +{leg1.get('edge', 0)*100:.1f}%",
        f"  Model: {leg1.get('model_prob', 0)*100:.1f}% | Confidence: {leg1_conf}",
        "",
        f"**LEG 2:** {leg2.get('outcome', '?')} {leg2.get('market', '')} "
        f"({leg2.get('odds', 0):+d}) | Edge: +{leg2.get('edge', 0)*100:.1f}%",
        f"  Model: {leg2.get('model_prob', 0)*100:.1f}% | Confidence: {leg2_conf}",
        "",
        f"**PARLAY:** {parlay_american:+d} | Combined Edge: "
        f"+{parlay_edge*100:.1f}%",
        "",
        f"Win: ${bankroll:.2f} -> ${next_step_val:.2f} (Step {step + 1})",
        f"Loss: Reset to ${ladder.get('starting_amount', 10.0):.2f} "
        f"(Attempt #{attempt + 1})",
        "",
        f"Shadow Portfolio: {sw}W-{sl}L | ${sp:+.2f} | ROI: {sr:+.1f}%",
        "",
        "NOTE: Odds shown from DraftKings. Verify on FanDuel before placing.",
    ]

    return {
        "embeds": [
            {
                "title": f"LADDERBOT -- Step {step} of {total}",
                "description": "\n".join(description_lines),
                "color": 0x00FF00,  # Green
            }
        ],
    }


def format_result_embed(
    parlay: dict,
    result: str,
    ladder: dict,
) -> dict:
    """Format a result notification as a Discord embed.

    Args:
        parlay: Parlay dict with leg1, leg2, parlay_american.
        result: 'won' or 'lost'.
        ladder: Ladder display dict.

    Returns:
        Discord embed dict.
    """
    leg1 = parlay.get("leg1", {})
    leg2 = parlay.get("leg2", {})
    parlay_american = parlay.get("parlay_american", 0)

    if result == "won":
        color = 0x00FF00
        emoji = "WIN"
        status_line = (
            f"Ladder advances to Step {ladder.get('current_step', 0)} | "
            f"Bankroll: ${ladder.get('current_bankroll', 0):.2f}"
        )
    else:
        color = 0xFF0000
        emoji = "LOSS"
        status_line = (
            f"Ladder resets. Starting Attempt #{ladder.get('attempt_number', 0) + 1}"
        )

    description_lines = [
        f"**{leg1.get('outcome', '?')}** {leg1.get('market', '')} "
        f"({leg1.get('odds', 0):+d})",
        f"**{leg2.get('outcome', '?')}** {leg2.get('market', '')} "
        f"({leg2.get('odds', 0):+d})",
        f"Parlay: {parlay_american:+d}",
        "",
        status_line,
    ]

    return {
        "embeds": [
            {
                "title": f"LADDERBOT RESULT -- {emoji}",
                "description": "\n".join(description_lines),
                "color": color,
            }
        ],
    }


def format_summary_embed(
    picks: list[dict],
    results: list[dict],
    portfolio: dict,
) -> dict:
    """Format a daily summary as a Discord embed.

    Args:
        picks: List of today's pick dicts.
        results: List of today's result dicts.
        portfolio: Shadow portfolio stats dict.

    Returns:
        Discord embed dict.
    """
    total_picks = len(picks)
    wins = sum(1 for r in results if r.get("result") == "won")
    losses = sum(1 for r in results if r.get("result") == "lost")

    sw = portfolio.get("wins", 0)
    sl = portfolio.get("losses", 0)
    sp = portfolio.get("profit", 0.0)
    sr = portfolio.get("roi", 0.0)

    description_lines = [
        f"**Picks today:** {total_picks}",
        f"**Results:** {wins}W-{losses}L",
        "",
        "**Shadow Portfolio (all-time)**",
        f"  Record: {sw}W-{sl}L | Profit: ${sp:+.2f} | ROI: {sr:+.1f}%",
    ]

    # Add individual results
    if results:
        description_lines.append("")
        description_lines.append("**Today's Results:**")
        for r in results:
            res_str = r.get("result", "pending").upper()
            description_lines.append(
                f"  {r.get('outcome', '?')} ({r.get('market', '')}) -- {res_str}"
            )

    return {
        "embeds": [
            {
                "title": "LADDERBOT -- Daily Summary",
                "description": "\n".join(description_lines),
                "color": 0x3498DB,  # Blue
            }
        ],
    }
