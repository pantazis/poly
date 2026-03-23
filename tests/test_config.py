"""Tests for TradingConfig and ConfigManager."""

import os
import tempfile
from pathlib import Path

import pytest

from src.trading.config import TradingConfig, ConfigManager, ConfigValidationError


class TestTradingConfigDefaults:
    """Test TradingConfig default values."""
    
    def test_default_entry_threshold_min(self):
        config = TradingConfig()
        assert config.entry_threshold_min == 25_000.0
    
    def test_default_entry_threshold_max(self):
        config = TradingConfig()
        assert config.entry_threshold_max == 100_000.0
    
    def test_default_liquidation_window_minutes(self):
        config = TradingConfig()
        assert config.liquidation_window_minutes == 5
    
    def test_default_bet_size(self):
        config = TradingConfig()
        assert config.bet_size == 10.0
    
    def test_default_discount_percent(self):
        config = TradingConfig()
        assert config.discount_percent == 10.0
    
    def test_default_polymarket_private_key(self):
        config = TradingConfig()
        assert config.polymarket_private_key == ""
    
    def test_default_hedge_leverage(self):
        config = TradingConfig()
        assert config.hedge_leverage == 3
    
    def test_default_hedge_size(self):
        config = TradingConfig()
        assert config.hedge_size == 15.0
    
    def test_default_binance_api_key(self):
        config = TradingConfig()
        assert config.binance_api_key == ""
    
    def test_default_binance_api_secret(self):
        config = TradingConfig()
        assert config.binance_api_secret == ""
    
    def test_default_max_daily_loss(self):
        config = TradingConfig()
        assert config.max_daily_loss == 100.0
    
    def test_default_max_concurrent_positions(self):
        config = TradingConfig()
        assert config.max_concurrent_positions == 1
    
    def test_default_dry_run(self):
        config = TradingConfig()
        assert config.dry_run is True

    def test_default_polymarket_live_data_in_dry_run(self):
        config = TradingConfig()
        assert config.polymarket_live_data_in_dry_run is True

    def test_default_binance_live_data_in_dry_run(self):
        config = TradingConfig()
        assert config.binance_live_data_in_dry_run is True
    
    def test_default_log_dir(self):
        config = TradingConfig()
        assert config.log_dir == Path("./logs")


class TestConfigManagerValidate:
    """Test ConfigManager.validate() method."""
    
    def test_valid_config_returns_empty_list(self):
        config = TradingConfig()
        errors = ConfigManager.validate(config)
        assert errors == []
    
    def test_entry_threshold_min_zero_invalid(self):
        config = TradingConfig(entry_threshold_min=0)
        errors = ConfigManager.validate(config)
        assert len(errors) == 1
        assert "entry_threshold_min" in errors[0]
    
    def test_entry_threshold_min_negative_invalid(self):
        config = TradingConfig(entry_threshold_min=-100)
        errors = ConfigManager.validate(config)
        assert any("entry_threshold_min" in e for e in errors)
    
    def test_entry_threshold_max_less_than_min_invalid(self):
        config = TradingConfig(
            entry_threshold_min=50_000,
            entry_threshold_max=25_000
        )
        errors = ConfigManager.validate(config)
        assert any("entry_threshold_max" in e for e in errors)
    
    def test_entry_threshold_max_equal_to_min_invalid(self):
        config = TradingConfig(
            entry_threshold_min=50_000,
            entry_threshold_max=50_000
        )
        errors = ConfigManager.validate(config)
        assert any("entry_threshold_max" in e for e in errors)
    
    def test_bet_size_zero_invalid(self):
        config = TradingConfig(bet_size=0)
        errors = ConfigManager.validate(config)
        assert any("bet_size" in e for e in errors)
    
    def test_bet_size_negative_invalid(self):
        config = TradingConfig(bet_size=-10)
        errors = ConfigManager.validate(config)
        assert any("bet_size" in e for e in errors)
    
    def test_hedge_leverage_zero_invalid(self):
        config = TradingConfig(hedge_leverage=0)
        errors = ConfigManager.validate(config)
        assert any("hedge_leverage" in e for e in errors)
    
    def test_hedge_leverage_21_invalid(self):
        config = TradingConfig(hedge_leverage=21)
        errors = ConfigManager.validate(config)
        assert any("hedge_leverage" in e for e in errors)
    
    def test_hedge_leverage_1_valid(self):
        config = TradingConfig(hedge_leverage=1)
        errors = ConfigManager.validate(config)
        assert not any("hedge_leverage" in e for e in errors)
    
    def test_hedge_leverage_20_valid(self):
        config = TradingConfig(hedge_leverage=20)
        errors = ConfigManager.validate(config)
        assert not any("hedge_leverage" in e for e in errors)
    
    def test_discount_percent_negative_invalid(self):
        config = TradingConfig(discount_percent=-1)
        errors = ConfigManager.validate(config)
        assert any("discount_percent" in e for e in errors)
    
    def test_discount_percent_51_invalid(self):
        config = TradingConfig(discount_percent=51)
        errors = ConfigManager.validate(config)
        assert any("discount_percent" in e for e in errors)
    
    def test_discount_percent_0_valid(self):
        config = TradingConfig(discount_percent=0)
        errors = ConfigManager.validate(config)
        assert not any("discount_percent" in e for e in errors)
    
    def test_discount_percent_50_valid(self):
        config = TradingConfig(discount_percent=50)
        errors = ConfigManager.validate(config)
        assert not any("discount_percent" in e for e in errors)
    
    def test_max_daily_loss_zero_invalid(self):
        config = TradingConfig(max_daily_loss=0)
        errors = ConfigManager.validate(config)
        assert any("max_daily_loss" in e for e in errors)
    
    def test_max_daily_loss_negative_invalid(self):
        config = TradingConfig(max_daily_loss=-50)
        errors = ConfigManager.validate(config)
        assert any("max_daily_loss" in e for e in errors)
    
    def test_multiple_errors_returned(self):
        config = TradingConfig(
            entry_threshold_min=0,
            bet_size=-10,
            hedge_leverage=25,
            max_daily_loss=-100
        )
        errors = ConfigManager.validate(config)
        assert len(errors) >= 4


class TestConfigManagerLoad:
    """Test ConfigManager.load() method."""
    
    def test_load_empty_yaml_uses_defaults(self):
        yaml_content = ""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = ConfigManager.load(Path(f.name))
        
        os.unlink(f.name)
        assert config.entry_threshold_min == 25_000.0
        assert config.bet_size == 10.0
        assert config.dry_run is True
    
    def test_load_partial_yaml_uses_defaults_for_missing(self):
        yaml_content = """
signal:
  entry_threshold_min: 30000
polymarket:
  bet_size: 20
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = ConfigManager.load(Path(f.name))
        
        os.unlink(f.name)
        assert config.entry_threshold_min == 30_000.0
        assert config.entry_threshold_max == 100_000.0  # default
        assert config.bet_size == 20.0
        assert config.discount_percent == 10.0  # default
    
    def test_load_full_yaml(self):
        yaml_content = "\n".join([
            "signal:",
            "  entry_threshold_min: 30000",
            "  entry_threshold_max: 150000",
            "  liquidation_window_minutes: 10",
            "polymarket:",
            "  bet_size: 25",
            "  discount_percent: 15",
            "  private_key: \"test_key\"",
            "binance:",
            "  hedge_leverage: 5",
            "  hedge_size: 20",
            "  api_key: \"binance_key\"",
            "  api_secret: \"binance_secret\"",
            "risk:",
            "  max_daily_loss: 200",
            "  max_concurrent_positions: 1",
            "operational:",
            "  dry_run: false",
            "  polymarket_live_data_in_dry_run: false",
            "  binance_live_data_in_dry_run: false",
            "  log_dir: \"./custom_logs\"",
            "",
        ])
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = ConfigManager.load(Path(f.name))
        
        os.unlink(f.name)
        assert config.entry_threshold_min == 30_000.0
        assert config.entry_threshold_max == 150_000.0
        assert config.liquidation_window_minutes == 10
        assert config.bet_size == 25.0
        assert config.discount_percent == 15.0
        assert config.polymarket_private_key == "test_key"
        assert config.hedge_leverage == 5
        assert config.hedge_size == 20.0
        assert config.binance_api_key == "binance_key"
        assert config.binance_api_secret == "binance_secret"
        assert config.max_daily_loss == 200.0
        assert config.max_concurrent_positions == 1
        assert config.dry_run is False
        assert config.polymarket_live_data_in_dry_run is False
        assert config.binance_live_data_in_dry_run is False
        assert config.log_dir == Path("./custom_logs")
    
    def test_load_with_env_var_substitution(self):
        os.environ['TEST_POLYMARKET_KEY'] = 'my_secret_key'
        os.environ['TEST_BINANCE_KEY'] = 'binance_api_key_123'
        
        yaml_content = """
polymarket:
  private_key: "${TEST_POLYMARKET_KEY}"
binance:
  api_key: "${TEST_BINANCE_KEY}"
"""
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                f.write(yaml_content)
                f.flush()
                config = ConfigManager.load(Path(f.name))
            
            os.unlink(f.name)
            assert config.polymarket_private_key == 'my_secret_key'
            assert config.binance_api_key == 'binance_api_key_123'
        finally:
            del os.environ['TEST_POLYMARKET_KEY']
            del os.environ['TEST_BINANCE_KEY']
    
    def test_load_with_missing_env_var_returns_empty(self):
        # Ensure the env var doesn't exist
        if 'NONEXISTENT_VAR_12345' in os.environ:
            del os.environ['NONEXISTENT_VAR_12345']
        
        yaml_content = """
polymarket:
  private_key: "${NONEXISTENT_VAR_12345}"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = ConfigManager.load(Path(f.name))
        
        os.unlink(f.name)
        assert config.polymarket_private_key == ''
    
    def test_load_invalid_config_raises_error(self):
        yaml_content = """
signal:
  entry_threshold_min: -100
polymarket:
  bet_size: 0
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            
            with pytest.raises(ConfigValidationError) as exc_info:
                ConfigManager.load(Path(f.name))
        
        os.unlink(f.name)
        assert len(exc_info.value.errors) >= 2
    
    def test_load_nonexistent_file_raises_error(self):
        with pytest.raises(FileNotFoundError):
            ConfigManager.load(Path("/nonexistent/path/config.yaml"))


class TestConfigValidationError:
    """Test ConfigValidationError exception."""
    
    def test_error_contains_all_messages(self):
        errors = ["error1", "error2", "error3"]
        exc = ConfigValidationError(errors)
        assert exc.errors == errors
        assert "error1" in str(exc)
        assert "error2" in str(exc)
        assert "error3" in str(exc)
