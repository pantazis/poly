"""Dry-run simulator that trades Polymarket BTC 5m markets using OBLM confidence logs.

Rules:
- Start with bankroll (default $100)
- Stake fixed percentage per trade (default 5%)
- Only open a trade when confidence gate passes:
  - latest snapshot has `general total trades >= 10`
  - and any available confidence threshold winrate is exactly 100%
- Ignore `empirical_winrate` for entry gating
- Use live read-only Polymarket prices in dry-run mode
- Settle after 5 minutes using BTC reference move when available;
  otherwise fallback to Polymarket quote relationship (UP vs DOWN)
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.trading.polymarket_connector import PolymarketConnector

logger = logging.getLogger(__name__)

_WIN_RE = re.compile(r"\bwinrate=([0-9]+(?:\.[0-9]+)?)%")
_TOTAL_RE = re.compile(r"\btotal=(\d+)")
_CONF_RE = re.compile(r"\bconfidence_gt=(\d+)")
_MINUTE_RE = re.compile(r"\bminute=([^\s]+)")
_SOURCE_RE = re.compile(r"\bsource=([^\s]+)")
_MOVE_RE = re.compile(r"\bmove=(UP|DOWN|HOLD)\b")
_ACTION_RE = re.compile(r"\baction=([A-Z_]+)\b")


def _parse_winrate_row(line: str) -> tuple[str, str, int, float, int] | None:
    """Parse a WINRATE row into (minute, source, confidence_gt, winrate, total)."""
    if "WINRATE" not in line:
        return None

    minute_match = _MINUTE_RE.search(line)
    source_match = _SOURCE_RE.search(line)
    conf_match = _CONF_RE.search(line)
    win_match = _WIN_RE.search(line)
    total_match = _TOTAL_RE.search(line)
    if (
        minute_match is None
        or source_match is None
        or conf_match is None
        or win_match is None
        or total_match is None
    ):
        return None

    return (
        minute_match.group(1),
        source_match.group(1),
        int(conf_match.group(1)),
        float(win_match.group(1)),
        int(total_match.group(1)),
    )


def parse_confidence90_winrate_from_line(line: str) -> float | None:
    """Parse confidence_gt=90 winrate from one WINRATE line."""
    row = _parse_winrate_row(line)
    if row is None:
        return None
    _, _, confidence_gt, winrate, _ = row
    if confidence_gt != 90:
        return None
    return winrate


def read_latest_gate_metrics(
    log_path: Path,
    confidence_thresholds: tuple[int, ...] = (90, 80, 70, 60, 50, 40, 30, 20, 10),
    min_confidence_winrate: float = 100.0,
) -> tuple[float, int, int] | None:
    """Read latest gate metrics from confidence log using threshold selection.

    Returns:
        Tuple of (selected_winrate, general_total_trades, selected_threshold)

    Gate rules:
    - select the highest threshold (priority order from confidence_thresholds)
      whose winrate is 100% (and >= min_confidence_winrate).
    - no baseline threshold is required.
    """
    if not log_path.exists():
        return None

    lines = log_path.read_text(encoding="utf-8").splitlines()
    snapshot_key: tuple[str, str] | None = None
    threshold_winrates: dict[int, float] = {}
    general_total_trades = 0

    for line in reversed(lines):
        row = _parse_winrate_row(line)
        if row is None:
            continue

        minute, source, confidence_gt, winrate, total = row
        key = (minute, source)

        if snapshot_key is None:
            snapshot_key = key

        if key != snapshot_key:
            break

        general_total_trades = max(general_total_trades, total)
        if confidence_gt in confidence_thresholds:
            threshold_winrates[confidence_gt] = winrate

    for threshold in confidence_thresholds:
        winrate = threshold_winrates.get(int(threshold))
        if winrate is None:
            continue
        if float(winrate) >= 100.0 and float(winrate) >= float(min_confidence_winrate):
            return float(winrate), general_total_trades, int(threshold)

    return None


def calculate_stake(bankroll: float, stake_pct: float) -> float:
    return max(0.0, bankroll * (stake_pct / 100.0))


@dataclass
class PendingTrade:
    trade_id: str
    opened_at: datetime
    outcome: str
    stake: float
    shares: float
    btc_entry_price: float | None = None


def choose_outcome_from_quotes(up_price: float, down_price: float, epsilon: float = 1e-9) -> str | None:
    """Choose direction from Polymarket quotes.

    Returns:
        "UP" when UP quote is higher,
        "DOWN" when DOWN quote is higher,
        None when quotes are effectively equal (no directional edge).
    """
    if abs(up_price - down_price) <= epsilon:
        return None
    return "UP" if up_price > down_price else "DOWN"


def choose_outcome_from_btc_move(
    btc_entry_price: float,
    btc_exit_price: float,
    epsilon: float = 1e-9,
) -> str | None:
    """Choose market winner from BTC move between entry and settlement.

    Returns:
        "UP" when BTC increased,
        "DOWN" when BTC decreased,
        None when prices are effectively equal (tie/no move).
    """
    delta = btc_exit_price - btc_entry_price
    if abs(delta) <= epsilon:
        return None
    return "UP" if delta > 0 else "DOWN"


def resolve_settlement_winner(
    btc_entry_price: float | None,
    btc_exit_price: float | None,
    up_exit_price: float,
    down_exit_price: float,
) -> str | None:
    """Resolve settlement winner, preferring BTC move when available.

    Priority:
    1) If both BTC entry/exit references are available, use BTC move.
    2) Otherwise, fallback to UP/DOWN quote relationship at settlement.
    """
    if btc_entry_price is not None and btc_exit_price is not None:
        return choose_outcome_from_btc_move(btc_entry_price, btc_exit_price)
    return choose_outcome_from_quotes(up_exit_price, down_exit_price)


def parse_decision_move_from_line(line: str) -> tuple[str, str] | None:
    """Parse OBLM DECISION line into (move, action).

    Accepts both formats:
    - DECISION ... move=DOWN action=TRADE ...
    - DECISION ... move=DOWN ... (legacy, action inferred)
    """
    if "DECISION" not in line:
        return None

    move_match = _MOVE_RE.search(line)
    if move_match is None:
        return None

    move = move_match.group(1)
    action_match = _ACTION_RE.search(line)
    if action_match is not None:
        action = action_match.group(1)
    else:
        action = "NO_TRADE" if move == "HOLD" else "TRADE"

    return move, action


def read_latest_model_outcome(decision_log_path: Path) -> str | None:
    """Read latest tradable UP/DOWN outcome from OBLM decisions log.

    Returns:
        "UP" or "DOWN" when latest decision is tradable,
        None when latest decision is NO_TRADE/HOLD or unavailable.
    """
    if not decision_log_path.exists():
        return None

    lines = decision_log_path.read_text(encoding="utf-8").splitlines()
    for line in reversed(lines):
        parsed = parse_decision_move_from_line(line)
        if parsed is None:
            continue

        move, action = parsed
        if action != "TRADE":
            return None
        if move in ("UP", "DOWN"):
            return move
        return None

    return None


async def run_simulator(
    confidence_log_path: str = "logs/oblm/confidence_winrate.log",
    decision_log_path: str = "logs/oblm/decisions.log",
    trades_csv_path: str = "logs/oblm/simulated_trades.csv",
    min_confidence_winrate: float = 100.0,
    min_total_trades: int = 10,
    confidence_thresholds: tuple[int, ...] = (90, 80, 70, 60, 50, 40, 30, 20, 10),
    initial_bankroll: float = 100.0,
    stake_pct: float = 5.0,
    settle_minutes: int = 5,
    poll_seconds: int = 30,
) -> None:
    log_path = Path(confidence_log_path)
    model_log_path = Path(decision_log_path)
    csv_path = Path(trades_csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    connector = PolymarketConnector(
        private_key="0" * 64,
        dry_run=True,
        use_live_market_data_in_dry_run=True,
    )
    await connector.connect()

    btc_price_source = None
    try:
        from src.trading.binance_trader import BinanceTrader

        btc_price_source = BinanceTrader(
            api_key="",
            api_secret="",
            dry_run=True,
            use_live_market_data_in_dry_run=True,
        )
    except ModuleNotFoundError as exc:
        logger.warning("SIM_BTC_REFERENCE disabled (dependency missing): %s", exc)

    notifier = None
    telegram_token = os.environ.get("TELEGRAM_TOKEN", "")
    telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if telegram_token and telegram_chat_id:
        try:
            from src.trading.telegram_notifier import TelegramNotifier

            notifier = TelegramNotifier(
                token=telegram_token,
                chat_id=telegram_chat_id,
                dry_run=True,
                enabled=True,
            )
            logger.info("SIM_TELEGRAM enabled=true")
        except ModuleNotFoundError as exc:
            logger.warning("SIM_TELEGRAM disabled (dependency missing): %s", exc)

    bankroll = float(initial_bankroll)
    session_pnl = 0.0
    pending: list[PendingTrade] = []
    horizon = timedelta(minutes=max(1, settle_minutes))

    if not csv_path.exists():
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([
                "timestamp",
                "trade_id",
                "outcome",
                "stake",
                "shares",
                "entry_up",
                "entry_down",
                "exit_up",
                "exit_down",
                "winner",
                "pnl",
                "bankroll",
                "confidence_winrate",
                "confidence_threshold",
                "total_trades",
            ])

    logger.info(
        "SIM_START bankroll=%.2f stake_pct=%.2f min_confidence_winrate=%.2f min_total_trades=%d thresholds=%s",
        bankroll,
        stake_pct,
        min_confidence_winrate,
        min_total_trades,
        ",".join(str(t) for t in confidence_thresholds),
    )

    try:
        while True:
            now = datetime.now(timezone.utc)

            # Settle matured trades
            still_open: list[PendingTrade] = []
            for t in pending:
                if now < t.opened_at + horizon:
                    still_open.append(t)
                    continue

                up_exit = await connector.get_current_price("UP")
                down_exit = await connector.get_current_price("DOWN")

                btc_exit_price: float | None = None
                if btc_price_source is not None:
                    try:
                        btc_exit_price = await btc_price_source.get_current_price("BTCUSDT")
                    except Exception as exc:
                        logger.warning("SIM_SETTLE failed to fetch BTC close reference: %s", exc)

                winner = resolve_settlement_winner(
                    btc_entry_price=t.btc_entry_price,
                    btc_exit_price=btc_exit_price,
                    up_exit_price=up_exit,
                    down_exit_price=down_exit,
                )
                payout = t.shares if (winner is not None and t.outcome == winner) else 0.0
                pnl = payout - t.stake
                bankroll += pnl
                session_pnl += pnl

                winner_label = winner or "TIE"

                with csv_path.open("a", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow([
                        now.isoformat(),
                        t.trade_id,
                        t.outcome,
                        f"{t.stake:.6f}",
                        f"{t.shares:.6f}",
                        "",
                        "",
                        f"{up_exit:.6f}",
                        f"{down_exit:.6f}",
                        winner_label,
                        f"{pnl:.6f}",
                        f"{bankroll:.6f}",
                        "",
                        "",
                        "",
                    ])

                logger.info(
                    "SIM_SETTLE trade_id=%s outcome=%s winner=%s pnl=%.4f bankroll=%.4f",
                    t.trade_id,
                    t.outcome,
                    winner_label,
                    pnl,
                    bankroll,
                )
                if notifier:
                    await notifier.send_trade_closed(
                        trade_id=t.trade_id,
                        polymarket_pnl=pnl,
                        binance_pnl=None,
                        total_pnl=pnl,
                        daily_pnl=session_pnl,
                        reference_entry_price=t.btc_entry_price,
                        reference_exit_price=btc_exit_price,
                    )

            pending = still_open

            # Entry gate from confidence log (any threshold can qualify)
            gate_metrics = read_latest_gate_metrics(
                log_path,
                confidence_thresholds=confidence_thresholds,
                min_confidence_winrate=min_confidence_winrate,
            )
            if gate_metrics is None:
                logger.info(
                    "SIM_SKIP reason=gate_not_passed min_confidence_winrate=%.2f thresholds=%s",
                    float(min_confidence_winrate),
                    ",".join(str(t) for t in confidence_thresholds),
                )
                await asyncio.sleep(max(5, poll_seconds))
                continue

            confidence_winrate, total_trades, used_threshold = gate_metrics
            if total_trades < int(min_total_trades):
                await asyncio.sleep(max(5, poll_seconds))
                continue

            # Keep simulator separate and simple: 1 open trade at a time
            if pending:
                await asyncio.sleep(max(5, poll_seconds))
                continue

            stake = calculate_stake(bankroll, stake_pct)
            if stake <= 0.0:
                logger.warning("SIM_STOP bankroll depleted")
                return

            up = await connector.get_current_price("UP")
            down = await connector.get_current_price("DOWN")
            outcome = read_latest_model_outcome(model_log_path)
            if outcome is None:
                logger.info("SIM_SKIP reason=no_tradable_model_decision")
                await asyncio.sleep(max(5, poll_seconds))
                continue

            btc_entry_price: float | None = None
            if btc_price_source is not None:
                try:
                    btc_entry_price = await btc_price_source.get_current_price("BTCUSDT")
                except Exception as exc:
                    logger.warning("SIM_OPEN failed to fetch BTC open reference: %s", exc)

            order = await connector.place_order(outcome=outcome, size=stake, discount_percent=0.0)

            shares = float(order.shares_bought or (stake / max(order.fill_price or 0.5, 1e-9)))
            pending.append(
                PendingTrade(
                    trade_id=order.order_id,
                    opened_at=now,
                    outcome=outcome,
                    stake=stake,
                    shares=shares,
                    btc_entry_price=btc_entry_price,
                )
            )

            with csv_path.open("a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([
                    now.isoformat(),
                    order.order_id,
                    outcome,
                    f"{stake:.6f}",
                    f"{shares:.6f}",
                    f"{up:.6f}",
                    f"{down:.6f}",
                    "",
                    "",
                    "",
                    "",
                    f"{bankroll:.6f}",
                    f"{confidence_winrate:.4f}",
                    f"{used_threshold}",
                    f"{total_trades}",
                ])

            logger.info(
                "SIM_OPEN trade_id=%s outcome=%s stake=%.4f bankroll=%.4f confidence_winrate=%.2f threshold=%d total_trades=%d",
                order.order_id,
                outcome,
                stake,
                bankroll,
                confidence_winrate,
                used_threshold,
                total_trades,
            )
            if notifier:
                await notifier.send_trade_entry(
                    trade_id=order.order_id,
                    direction=outcome,
                    entry_price=order.fill_price or order.price,
                    bet_size=stake,
                    reference_entry_price=btc_entry_price,
                    shares_bought=order.shares_bought,
                    max_profit=order.max_profit,
                    max_loss=order.max_loss,
                )

            await asyncio.sleep(max(5, poll_seconds))
    finally:
        if notifier:
            await notifier.close()
        if btc_price_source is not None:
            await btc_price_source.close()
        await connector.close()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="OBLM dry-run Polymarket simulator")
    p.add_argument("--confidence-log-path", default="logs/oblm/confidence_winrate.log")
    p.add_argument("--decision-log-path", default="logs/oblm/decisions.log")
    p.add_argument("--trades-csv-path", default="logs/oblm/simulated_trades.csv")
    p.add_argument(
        "--min-confidence-winrate",
        "--min-confidence90-winrate",
        dest="min_confidence_winrate",
        type=float,
        default=100.0,
        help="Minimum required winrate for selected confidence threshold (use 100 for PLAY-only-on-100%% rule)",
    )
    p.add_argument("--min-total-trades", type=int, default=10)
    p.add_argument(
        "--confidence-thresholds",
        default="90,80,70,60,50,40,30,20,10",
        help="Comma-separated confidence thresholds (priority order), e.g. 90,80,...,10",
    )
    p.add_argument("--initial-bankroll", type=float, default=100.0)
    p.add_argument("--stake-pct", type=float, default=5.0)
    p.add_argument("--settle-minutes", type=int, default=5)
    p.add_argument("--poll-seconds", type=int, default=30)
    return p.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    args = _parse_args()
    confidence_thresholds = tuple(
        int(x.strip())
        for x in str(args.confidence_thresholds).split(",")
        if x.strip()
    )
    if not confidence_thresholds:
        confidence_thresholds = (90, 80, 70, 60, 50, 40, 30, 20, 10)
    asyncio.run(
        run_simulator(
            confidence_log_path=args.confidence_log_path,
            decision_log_path=args.decision_log_path,
            trades_csv_path=args.trades_csv_path,
            min_confidence_winrate=args.min_confidence_winrate,
            min_total_trades=args.min_total_trades,
            confidence_thresholds=confidence_thresholds,
            initial_bankroll=args.initial_bankroll,
            stake_pct=args.stake_pct,
            settle_minutes=args.settle_minutes,
            poll_seconds=args.poll_seconds,
        )
    )


if __name__ == "__main__":
    main()
