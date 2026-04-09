from pathlib import Path

from src.trading.oblm_simulator import (
    calculate_stake,
    choose_outcome_from_btc_move,
    choose_outcome_from_quotes,
    parse_decision_move_from_line,
    parse_confidence90_winrate_from_line,
    read_latest_model_outcome,
    read_latest_gate_metrics,
    resolve_settlement_winner,
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


def test_read_latest_gate_metrics_uses_latest_snapshot_and_selects_highest_passing_threshold(tmp_path: Path):
    log = tmp_path / "confidence.log"
    log.write_text(
        "abc\n"
        "WINRATE minute=t1 source=settlement confidence_gt=90 wins=7 total=10 winrate=70.00%\n"
        "WINRATE minute=t2 source=settlement confidence_gt=90 wins=20 total=20 winrate=100.00%\n"
        "WINRATE minute=t2 source=settlement confidence_gt=80 wins=24 total=30 winrate=80.00%\n"
        "WINRATE minute=t2 source=settlement confidence_gt=10 wins=95 total=100 winrate=95.00% empirical_winrate=42.00%\n",
        encoding="utf-8",
    )
    assert read_latest_gate_metrics(log, min_confidence_winrate=55.0) == (100.0, 100, 90)


def test_read_latest_gate_metrics_selects_conf80_when_90_below_100(tmp_path: Path):
    log = tmp_path / "confidence.log"
    log.write_text(
        "WINRATE minute=t2 source=settlement confidence_gt=90 wins=12 total=20 winrate=60.00%\n"
        "WINRATE minute=t2 source=settlement confidence_gt=80 wins=30 total=30 winrate=100.00%\n"
        "WINRATE minute=t2 source=settlement confidence_gt=10 wins=98 total=100 winrate=98.00%\n",
        encoding="utf-8",
    )
    assert read_latest_gate_metrics(log, min_confidence_winrate=65.0) == (100.0, 100, 80)


def test_read_latest_gate_metrics_selects_highest_passing_threshold_without_baseline_requirement(tmp_path: Path):
    log = tmp_path / "confidence.log"
    log.write_text(
        "WINRATE minute=t2 source=settlement confidence_gt=90 wins=30 total=30 winrate=100.00%\n"
        "WINRATE minute=t2 source=settlement confidence_gt=70 wins=24 total=30 winrate=80.00%\n",
        encoding="utf-8",
    )
    assert read_latest_gate_metrics(log) == (100.0, 30, 90)


def test_read_latest_gate_metrics_ignores_baseline_threshold_10_when_higher_threshold_passes(tmp_path: Path):
    log = tmp_path / "confidence.log"
    log.write_text(
        "WINRATE minute=t2 source=settlement confidence_gt=90 wins=30 total=30 winrate=100.00%\n"
        "WINRATE minute=t2 source=settlement confidence_gt=10 wins=55 total=100 winrate=55.00%\n",
        encoding="utf-8",
    )
    assert read_latest_gate_metrics(log, min_confidence_winrate=65.0) == (100.0, 100, 90)


def test_read_latest_gate_metrics_returns_none_when_no_threshold_hits_100(tmp_path: Path):
    log = tmp_path / "confidence.log"
    log.write_text(
        "WINRATE minute=t2 source=settlement confidence_gt=90 wins=6 total=20 winrate=30.00%\n"
        "WINRATE minute=t2 source=settlement confidence_gt=80 wins=10 total=20 winrate=50.00%\n"
        "WINRATE minute=t2 source=settlement confidence_gt=10 wins=99 total=100 winrate=99.00%\n",
        encoding="utf-8",
    )
    assert read_latest_gate_metrics(log, min_confidence_winrate=70.0) is None


def test_read_latest_gate_metrics_returns_none_when_min_confidence_winrate_is_above_100(tmp_path: Path):
    log = tmp_path / "confidence.log"
    log.write_text(
        "WINRATE minute=t2 source=settlement confidence_gt=90 wins=10 total=10 winrate=100.00%\n",
        encoding="utf-8",
    )
    assert read_latest_gate_metrics(log, min_confidence_winrate=101.0) is None


def test_calculate_stake_percent():
    assert calculate_stake(100.0, 5.0) == 5.0


def test_choose_outcome_from_quotes_up_when_up_quote_higher():
    assert choose_outcome_from_quotes(0.61, 0.39) == "UP"


def test_choose_outcome_from_quotes_down_when_down_quote_higher():
    assert choose_outcome_from_quotes(0.41, 0.59) == "DOWN"


def test_choose_outcome_from_quotes_returns_none_when_equal_quotes():
    assert choose_outcome_from_quotes(0.50, 0.50) is None


def test_choose_outcome_from_btc_move_up_when_price_increases():
    assert choose_outcome_from_btc_move(69000.0, 69100.0) == "UP"


def test_choose_outcome_from_btc_move_down_when_price_decreases():
    assert choose_outcome_from_btc_move(69000.0, 68900.0) == "DOWN"


def test_choose_outcome_from_btc_move_returns_none_when_flat():
    assert choose_outcome_from_btc_move(69000.0, 69000.0) is None


def test_resolve_settlement_winner_prefers_btc_when_available():
    # BTC says DOWN, even though quote relationship points UP
    assert (
        resolve_settlement_winner(
            btc_entry_price=69000.0,
            btc_exit_price=68900.0,
            up_exit_price=0.61,
            down_exit_price=0.39,
        )
        == "DOWN"
    )


def test_resolve_settlement_winner_falls_back_to_quotes_without_btc():
    assert (
        resolve_settlement_winner(
            btc_entry_price=None,
            btc_exit_price=None,
            up_exit_price=0.41,
            down_exit_price=0.59,
        )
        == "DOWN"
    )


def test_resolve_settlement_winner_returns_none_for_tie_without_btc():
    assert (
        resolve_settlement_winner(
            btc_entry_price=None,
            btc_exit_price=None,
            up_exit_price=0.50,
            down_exit_price=0.50,
        )
        is None
    )


def test_parse_decision_move_from_line_trade_down():
    line = (
        "DECISION minute=2026-04-06T06:25:00+00:00 move=DOWN action=TRADE "
        "probability=78.80%"
    )
    assert parse_decision_move_from_line(line) == ("DOWN", "TRADE")


def test_parse_decision_move_from_line_legacy_hold_infers_no_trade():
    line = "DECISION minute=2026-04-06T06:25:00+00:00 move=HOLD probability=55.00%"
    assert parse_decision_move_from_line(line) == ("HOLD", "NO_TRADE")


def test_read_latest_model_outcome_returns_last_tradeable_move(tmp_path: Path):
    log = tmp_path / "decisions.log"
    log.write_text(
        "INFO DECISION minute=t1 move=UP action=NO_TRADE probability=51.00%\n"
        "INFO DECISION minute=t2 move=DOWN action=TRADE probability=78.80%\n",
        encoding="utf-8",
    )
    assert read_latest_model_outcome(log) == "DOWN"


def test_read_latest_model_outcome_returns_none_for_no_trade(tmp_path: Path):
    log = tmp_path / "decisions.log"
    log.write_text(
        "INFO DECISION minute=t2 move=HOLD action=NO_TRADE probability=78.80%\n",
        encoding="utf-8",
    )
    assert read_latest_model_outcome(log) is None
