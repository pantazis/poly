"""Tests for DataNormalizer."""

from datetime import datetime, timezone

from src.normalizer import DataNormalizer


def test_normalize_binance_long_liquidation():
    """Test normalizing a long liquidation (SELL side)."""
    raw = {
        "e": "forceOrder",
        "E": 1568014460893,
        "o": {
            "s": "BTCUSDT",
            "S": "SELL",
            "o": "LIMIT",
            "f": "IOC",
            "q": "0.014",
            "p": "9910",
            "ap": "9910",
            "X": "FILLED",
            "l": "0.014",
            "z": "0.014",
            "T": 1568014460893,
        }
    }
    
    event = DataNormalizer.normalize_binance(raw)
    
    assert event.exchange == "binance"
    assert event.symbol == "BTCUSDT"
    assert event.side == "long_liquidated"
    assert event.usd_size == 0.014 * 9910
    assert event.price == 9910.0
    assert event.is_significant is False


def test_normalize_binance_short_liquidation():
    """Test normalizing a short liquidation (BUY side)."""
    raw = {
        "e": "forceOrder",
        "E": 1700000000000,
        "o": {
            "s": "ETHUSDT",
            "S": "BUY",
            "o": "LIMIT",
            "f": "IOC",
            "q": "1.5",
            "p": "2000",
            "ap": "2000",
            "X": "FILLED",
            "l": "1.5",
            "z": "1.5",
            "T": 1700000000000,
        }
    }
    
    event = DataNormalizer.normalize_binance(raw)
    
    assert event.side == "short_liquidated"
    assert event.usd_size == 1.5 * 2000


def test_serialization_round_trip():
    """Test that to_dict and from_dict are inverses."""
    raw = {
        "e": "forceOrder",
        "E": 1568014460893,
        "o": {
            "s": "BTCUSDT",
            "S": "SELL",
            "o": "LIMIT",
            "f": "IOC",
            "q": "0.5",
            "p": "50000",
            "ap": "50000",
            "X": "FILLED",
            "l": "0.5",
            "z": "0.5",
            "T": 1568014460893,
        }
    }
    
    original = DataNormalizer.normalize_binance(raw)
    serialized = DataNormalizer.to_dict(original)
    restored = DataNormalizer.from_dict(serialized)
    
    assert restored.exchange == original.exchange
    assert restored.symbol == original.symbol
    assert restored.side == original.side
    assert restored.usd_size == original.usd_size
    assert restored.price == original.price
    assert restored.time == original.time
    assert restored.is_significant == original.is_significant
