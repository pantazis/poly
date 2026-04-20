"""Configuration management for the Liquidation Trading Bot.

This module provides:
- TradingConfig: Dataclass with all configurable parameters and defaults
- ConfigManager: Loads and validates configuration from YAML files
- ConfigValidationError: Exception for invalid configuration values
"""

from dataclasses import dataclass, field
from pathlib import Path
import os
import re


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""
    
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"Configuration validation failed: {'; '.join(errors)}")


@dataclass
class TradingConfig:
    """Trading bot configuration with all parameters and defaults.
    
    Attributes:
        entry_threshold_min: Minimum liquidation USD to trigger signal
        entry_threshold_max: Maximum liquidation USD for valid signal
        liquidation_window_minutes: Aggregation window to monitor (1, 5, 10, or 15)
        bet_size: USDC amount to bet on Polymarket
        discount_percent: Percentage below best ask for limit price
        polymarket_private_key: Ethereum wallet private key for EIP-712 signing
        hedge_leverage: Binance Futures leverage multiplier
        hedge_size: USD value for Binance hedge position
        binance_api_key: Binance API key
        binance_api_secret: Binance API secret for HMAC signing
        max_daily_loss: Maximum daily realized loss in USD
        max_concurrent_positions: Maximum open TradePairs (always 1)
        dry_run: If True, simulate trades without API calls
        log_dir: Directory for trade log CSV files
    """
    
    # Signal detection
    entry_threshold_min: float = 25_000.0
    entry_threshold_max: float = 100_000.0
    liquidation_window_minutes: int = 5
    
    # Polymarket
    bet_size: float = 10.0
    discount_percent: float = 10.0
    polymarket_private_key: str = ""
    
    # Binance
    hedge_enabled: bool = True
    hedge_leverage: int = 3
    hedge_size: float = 15.0
    binance_api_key: str = ""
    binance_api_secret: str = ""
    
    # Risk
    max_daily_loss: float = 100.0
    max_concurrent_positions: int = 1
    
    # Operational
    dry_run: bool = True
    training_mode: bool = False
    polymarket_live_data_in_dry_run: bool = True
    binance_live_data_in_dry_run: bool = True
    log_dir: Path = field(default_factory=lambda: Path("./logs"))
    
    # Telegram
    telegram_enabled: bool = False
    telegram_token: str = ""
    telegram_chat_id: str = ""


class ConfigManager:
    """Loads and validates configuration from YAML files."""
    
    # Pattern for environment variable substitution: ${VAR_NAME}
    _ENV_VAR_PATTERN = re.compile(r'\$\{([^}]+)\}')
    
    @staticmethod
    def _substitute_env_vars(value: str) -> str:
        """Substitute ${VAR_NAME} patterns with environment variable values.
        
        Args:
            value: String potentially containing ${VAR_NAME} patterns
            
        Returns:
            String with environment variables substituted
        """
        def replace_match(match: re.Match) -> str:
            var_name = match.group(1)
            return os.environ.get(var_name, "")
        
        return ConfigManager._ENV_VAR_PATTERN.sub(replace_match, value)
    
    @staticmethod
    def _process_value(value):
        """Process a value, substituting environment variables if it's a string."""
        if isinstance(value, str):
            return ConfigManager._substitute_env_vars(value)
        return value

    @staticmethod
    def _to_bool(value) -> bool:
        """Convert common bool-like values reliably.

        Accepts bool, int/float, and strings like true/false/1/0/yes/no/on/off.
        """
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "y", "on"}:
                return True
            if normalized in {"false", "0", "no", "n", "off", ""}:
                return False
        return bool(value)
    
    @staticmethod
    def load(config_path: Path) -> TradingConfig:
        """Load configuration from YAML file.
        
        Missing values use defaults from TradingConfig.
        Supports environment variable substitution with ${VAR_NAME} syntax.
        
        Args:
            config_path: Path to YAML configuration file
            
        Returns:
            TradingConfig with loaded values
            
        Raises:
            ConfigValidationError: If values are invalid
            FileNotFoundError: If config file doesn't exist
        """
        # Import yaml here to avoid hard dependency if not using YAML
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "PyYAML is required for configuration loading. "
                "Install with: pip install pyyaml"
            )
        
        with open(config_path, 'r') as f:
            raw_config = yaml.safe_load(f) or {}
        
        # Build config dict from nested YAML structure
        config_dict = {}
        
        # Signal section
        signal = raw_config.get('signal', {})
        if 'entry_threshold_min' in signal:
            config_dict['entry_threshold_min'] = float(signal['entry_threshold_min'])
        if 'entry_threshold_max' in signal:
            config_dict['entry_threshold_max'] = float(signal['entry_threshold_max'])
        if 'liquidation_window_minutes' in signal:
            config_dict['liquidation_window_minutes'] = int(signal['liquidation_window_minutes'])
        
        # Polymarket section
        polymarket = raw_config.get('polymarket', {})
        if 'bet_size' in polymarket:
            config_dict['bet_size'] = float(polymarket['bet_size'])
        if 'discount_percent' in polymarket:
            config_dict['discount_percent'] = float(polymarket['discount_percent'])
        if 'private_key' in polymarket:
            config_dict['polymarket_private_key'] = ConfigManager._process_value(
                polymarket['private_key']
            )
        
        # Binance section
        binance = raw_config.get('binance', {})
        if 'hedge_enabled' in binance:
            config_dict['hedge_enabled'] = ConfigManager._to_bool(binance['hedge_enabled'])
        if 'hedge_leverage' in binance:
            config_dict['hedge_leverage'] = int(binance['hedge_leverage'])
        if 'hedge_size' in binance:
            config_dict['hedge_size'] = float(binance['hedge_size'])
        if 'api_key' in binance:
            config_dict['binance_api_key'] = ConfigManager._process_value(
                binance['api_key']
            )
        if 'api_secret' in binance:
            config_dict['binance_api_secret'] = ConfigManager._process_value(
                binance['api_secret']
            )
        
        # Risk section
        risk = raw_config.get('risk', {})
        if 'max_daily_loss' in risk:
            config_dict['max_daily_loss'] = float(risk['max_daily_loss'])
        if 'max_concurrent_positions' in risk:
            config_dict['max_concurrent_positions'] = int(risk['max_concurrent_positions'])
        
        # Operational section
        operational = raw_config.get('operational', {})
        if 'dry_run' in operational:
            config_dict['dry_run'] = ConfigManager._to_bool(operational['dry_run'])
        if 'training_mode' in operational:
            config_dict['training_mode'] = ConfigManager._to_bool(operational['training_mode'])
        if 'polymarket_live_data_in_dry_run' in operational:
            config_dict['polymarket_live_data_in_dry_run'] = ConfigManager._to_bool(
                operational['polymarket_live_data_in_dry_run']
            )
        if 'binance_live_data_in_dry_run' in operational:
            config_dict['binance_live_data_in_dry_run'] = ConfigManager._to_bool(
                operational['binance_live_data_in_dry_run']
            )
        if 'log_dir' in operational:
            log_dir_value = ConfigManager._process_value(operational['log_dir'])
            config_dict['log_dir'] = Path(log_dir_value)
        
        # Telegram section
        telegram = raw_config.get('telegram', {})
        if 'enabled' in telegram:
            config_dict['telegram_enabled'] = ConfigManager._to_bool(telegram['enabled'])
        if 'token' in telegram:
            config_dict['telegram_token'] = ConfigManager._process_value(
                telegram['token']
            )
        if 'chat_id' in telegram:
            config_dict['telegram_chat_id'] = ConfigManager._process_value(
                telegram['chat_id']
            )
        
        # Create config with defaults for missing values
        config = TradingConfig(**config_dict)

        # Training mode safety: never use Polymarket API and keep simulation mode.
        if config.training_mode:
            config.dry_run = True
            config.polymarket_live_data_in_dry_run = False
        
        # Validate and raise if errors
        errors = ConfigManager.validate(config)
        if errors:
            raise ConfigValidationError(errors)
        
        return config
    
    @staticmethod
    def validate(config: TradingConfig) -> list[str]:
        """Validate configuration values.
        
        Args:
            config: TradingConfig to validate
            
        Returns:
            List of error messages (empty if valid)
            
        Validation rules:
        - entry_threshold_min > 0
        - entry_threshold_max > entry_threshold_min
        - bet_size > 0
        - hedge_leverage >= 1 and <= 20
        - discount_percent >= 0 and <= 50
        - max_daily_loss > 0
        """
        errors = []
        
        # entry_threshold_min > 0
        if config.entry_threshold_min <= 0:
            errors.append(
                f"entry_threshold_min must be > 0, got {config.entry_threshold_min}"
            )
        
        # entry_threshold_max > entry_threshold_min
        if config.entry_threshold_max <= config.entry_threshold_min:
            errors.append(
                f"entry_threshold_max ({config.entry_threshold_max}) must be > "
                f"entry_threshold_min ({config.entry_threshold_min})"
            )
        
        # bet_size > 0
        if config.bet_size <= 0:
            errors.append(f"bet_size must be > 0, got {config.bet_size}")
        
        # hedge_leverage >= 1 and <= 20
        if config.hedge_leverage < 1 or config.hedge_leverage > 20:
            errors.append(
                f"hedge_leverage must be >= 1 and <= 20, got {config.hedge_leverage}"
            )
        
        # discount_percent >= 0 and <= 50
        if config.discount_percent < 0 or config.discount_percent > 50:
            errors.append(
                f"discount_percent must be >= 0 and <= 50, got {config.discount_percent}"
            )
        
        # max_daily_loss > 0
        if config.max_daily_loss <= 0:
            errors.append(f"max_daily_loss must be > 0, got {config.max_daily_loss}")
        
        return errors
