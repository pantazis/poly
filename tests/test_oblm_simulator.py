from pathlib import Path

from src.trading.oblm_simulator import (
    calculate_stake,
    parse_confidence90_winrate_from_line,
    read_latest_gate_metrics,
)


def test_parse_confidence90_winrate_from_line_only_reads_conf_90():
    line = (
        "WINRATE minute=2026 source=heartbeat confidence_gt=90 "
        "wins=13 total=20 winrate=65.00% empirical_winrate=55.00%"
    )
    assert parse_confidence90_winrate_from_line(line) == 65.0


def test_parse_confidence90_winrate_from_line_ignores_other_thresholds():
    line = "WINRATE minute=2026 source=heartbeat confidence_gt=80 wins=40 total=60 winrate=66.67%"
    assert parse_confidence90_winrate_from_line(line) is None


def test_read_latest_gate_metrics_uses_latest_snapshot_general_total_and_conf90(tmp_path: Path):
    log = tmp_path / "confidence.log"
    log.write_text(
        "abc\n"
        "WINRATE minute=t1 source=settlement confidence_gt=90 wins=7 total=10 winrate=70.00%\n"
        "WINRATE minute=t2 source=settlement confidence_gt=90 wins=13 total=20 winrate=65.00%\n"
        "WINRATE minute=t2 source=settlement confidence_gt=80 wins=24 total=30 winrate=80.00%\n"
        "WINRATE minute=t2 source=settlement confidence_gt=10 wins=55 total=100 winrate=55.00% empirical_winrate=42.00%\n",
        encoding="utf-8",
    )
    assert read_latest_gate_metrics(log) == (65.0, 100)


def test_read_latest_gate_metrics_returns_none_without_conf90_in_latest_snapshot(tmp_path: Path):
    log = tmp_path / "confidence.log"
    log.write_text(
        "WINRATE minute=t2 source=settlement confidence_gt=80 wins=24 total=30 winrate=80.00%\n"
        "WINRATE minute=t2 source=settlement confidence_gt=10 wins=55 total=100 winrate=55.00%\n",
        encoding="utf-8",
    )
    assert read_latest_gate_metrics(log) is None


def test_calculate_stake_percent():
    assert calculate_stake(100.0, 5.0) == 5.0
