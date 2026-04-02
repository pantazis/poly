from pathlib import Path

from src.trading.oblm_simulator import (
    calculate_stake,
    parse_empirical_winrate_from_line,
    read_latest_empirical_winrate,
)


def test_parse_empirical_winrate_from_line_prefers_empirical():
    line = (
        "WINRATE_VOL2H_CONF minute=2026 source=heartbeat bucket=NA confidence_gt=10 "
        "wins=66 total=100 winrate=66.00% empirical_winrate=67.25%"
    )
    assert parse_empirical_winrate_from_line(line) == 67.25


def test_read_latest_empirical_winrate_reads_last_winrate_line(tmp_path: Path):
    log = tmp_path / "confidence.log"
    log.write_text(
        "abc\n"
        "WINRATE minute=t1 source=s confidence_gt=10 wins=1 total=2 winrate=50.00%\n"
        "WINRATE minute=t2 source=s confidence_gt=10 wins=7 total=10 winrate=70.00% empirical_winrate=70.00%\n",
        encoding="utf-8",
    )
    assert read_latest_empirical_winrate(log) == 70.0


def test_calculate_stake_percent():
    assert calculate_stake(100.0, 5.0) == 5.0
