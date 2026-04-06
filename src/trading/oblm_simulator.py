"""Dry-run simulator that trades Polymarket BTC 5m markets using OBLM confidence logs.

Rules:
- Start with bankroll (default $100)
- Stake fixed percentage per trade (default 5%)
- Only open a trade when confidence gate passes:
  - latest snapshot has `general total trades >= 20`
  - and latest `confidence_gt=90` `winrate >= 65%`
- Ignore `empirical_winrate` for entry gating
- Use live read-only Polymarket prices in dry-run mode
- Settle after 5 minutes based on which side (UP/DOWN) has higher price
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


def read_latest_gate_metrics(log_path: Path) -> tuple[float, int] | None:
    """Read latest (confidence90_winrate, general_total_trades) from confidence log.

    - confidence90_winrate: from confidence_gt=90 row in latest snapshot
    - general_total_trades: max total among all confidence rows in latest snapshot
    """
    if not log_path.exists():
        return None

    lines = log_path.read_text(encoding="utf-8").splitlines()
    snapshot_key: tuple[str, str] | None = None
    confidence90_winrate: float | None = None
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
        if confidence_gt == 90:
            confidence90_winrate = winrate

    if confidence90_winrate is None:
        return None
    return confidence90_winrate, general_total_trades


def calculate_stake(bankroll: float, stake_pct: float) -> float:
    return max(0.0, bankroll * (stake_pct / 100.0))


@dataclass
class PendingTrade:
    trade_id: str
    opened_at: datetime
    outcome: str
    stake: float
    shares: float


async def run_simulator(
    confidence_log_path: str = "logs/oblm/confidence_winrate.log",
    trades_csv_path: str = "logs/oblm/simulated_trades.csv",
    min_confidence90_winrate: float = 65.0,
    min_total_trades: int = 20,
    initial_bankroll: float = 100.0,
    stake_pct: float = 5.0,
    settle_minutes: int = 5,
    poll_seconds: int = 30,
) -> None:
    log_path = Path(confidence_log_path)
    csv_path = Path(trades_csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    connector = PolymarketConnector(
        private_key="0" * 64,
        dry_run=True,
        use_live_market_data_in_dry_run=True,
    )
    await connector.connect()

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
                "confidence90_winrate",
                "total_trades",
            ])

    logger.info(
        "SIM_START bankroll=%.2f stake_pct=%.2f min_confidence90_winrate=%.2f min_total_trades=%d",
        bankroll,
        stake_pct,
        min_confidence90_winrate,
        min_total_trades,
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
                winner = "UP" if up_exit >= down_exit else "DOWN"
                payout = t.shares if t.outcome == winner else 0.0
                pnl = payout - t.stake
                bankroll += pnl
                session_pnl += pnl

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
                        winner,
                        f"{pnl:.6f}",
                        f"{bankroll:.6f}",
                        "",
                        "",
                    ])

                logger.info(
                    "SIM_SETTLE trade_id=%s outcome=%s winner=%s pnl=%.4f bankroll=%.4f",
                    t.trade_id,
                    t.outcome,
                    winner,
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
                    )

            pending = still_open

            # Entry gate from confidence log (confidence_gt=90 only)
            gate_metrics = read_latest_gate_metrics(log_path)
            if gate_metrics is None:
                await asyncio.sleep(max(5, poll_seconds))
                continue

            confidence90_winrate, total_trades = gate_metrics
            if (
                total_trades < int(min_total_trades)
                or confidence90_winrate < float(min_confidence90_winrate)
            ):
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
            outcome = "UP" if up >= down else "DOWN"
            order = await connector.place_order(outcome=outcome, size=stake, discount_percent=0.0)

            shares = float(order.shares_bought or (stake / max(order.fill_price or 0.5, 1e-9)))
            pending.append(
                PendingTrade(
                    trade_id=order.order_id,
                    opened_at=now,
                    outcome=outcome,
                    stake=stake,
                    shares=shares,
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
                    f"{confidence90_winrate:.4f}",
                    f"{total_trades}",
                ])

            logger.info(
                "SIM_OPEN trade_id=%s outcome=%s stake=%.4f bankroll=%.4f confidence90_winrate=%.2f total_trades=%d",
                order.order_id,
                outcome,
                stake,
                bankroll,
                confidence90_winrate,
                total_trades,
            )
            if notifier:
                await notifier.send_trade_entry(
                    trade_id=order.order_id,
                    direction=outcome,
                    entry_price=order.fill_price or order.price,
                    bet_size=stake,
                    shares_bought=order.shares_bought,
                    max_profit=order.max_profit,
                    max_loss=order.max_loss,
                )

            await asyncio.sleep(max(5, poll_seconds))
    finally:
        if notifier:
            await notifier.close()
        await connector.close()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="OBLM dry-run Polymarket simulator")
    p.add_argument("--confidence-log-path", default="logs/oblm/confidence_winrate.log")
    p.add_argument("--trades-csv-path", default="logs/oblm/simulated_trades.csv")
    p.add_argument("--min-confidence90-winrate", type=float, default=65.0)
    p.add_argument("--min-total-trades", type=int, default=20)
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
    asyncio.run(
        run_simulator(
            confidence_log_path=args.confidence_log_path,
            trades_csv_path=args.trades_csv_path,
            min_confidence90_winrate=args.min_confidence90_winrate,
            min_total_trades=args.min_total_trades,
            initial_bankroll=args.initial_bankroll,
            stake_pct=args.stake_pct,
            settle_minutes=args.settle_minutes,
            poll_seconds=args.poll_seconds,
        )
    )


if __name__ == "__main__":
    main()
