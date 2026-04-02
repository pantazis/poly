"""Trading bot components for the Liquidation Trading Bot."""

from src.trading.config import TradingConfig, ConfigManager, ConfigValidationError

try:
    from src.trading.position_manager import PositionManager
except ModuleNotFoundError:  # pragma: no cover - optional runtime deps may be absent in tests
    PositionManager = None  # type: ignore[assignment]

try:
    from src.trading.risk_controller import RiskController
except ModuleNotFoundError:  # pragma: no cover - optional runtime deps may be absent in tests
    RiskController = None  # type: ignore[assignment]

try:
    from src.trading.signal_detector import SignalDetector
except ModuleNotFoundError:  # pragma: no cover - optional runtime deps may be absent in tests
    SignalDetector = None  # type: ignore[assignment]

try:
    from src.trading.telegram_command_handler import TelegramCommandHandler
except ModuleNotFoundError:  # pragma: no cover - optional runtime deps may be absent in tests
    TelegramCommandHandler = None  # type: ignore[assignment]

try:
    from src.trading.trade_logger import TradeLogger
except ModuleNotFoundError:  # pragma: no cover - optional runtime deps may be absent in tests
    TradeLogger = None  # type: ignore[assignment]

try:
    from src.trading.bot import TradingBot
except ModuleNotFoundError:  # pragma: no cover - optional runtime deps may be absent in tests
    TradingBot = None  # type: ignore[assignment]

__all__ = [
    "TradingBot",
    "TradingConfig",
    "ConfigManager",
    "ConfigValidationError",
    "PositionManager",
    "RiskController",
    "SignalDetector",
    "TelegramCommandHandler",
    "TradeLogger",
]
