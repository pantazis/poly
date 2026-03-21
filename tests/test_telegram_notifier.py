"""Tests for TelegramNotifier class.

Tests cover:
- Initialization with various parameters
- Message truncation
- Deduplication logic
- Disabled mode behavior
- Retry logic (mocked)
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.trading.telegram_notifier import TelegramNotifier


class TestTelegramNotifierInit:
    """Tests for TelegramNotifier initialization."""
    
    def test_init_stores_parameters(self):
        """Test that __init__ stores all parameters correctly."""
        notifier = TelegramNotifier(
            token="test_token",
            chat_id="123456",
            dry_run=True,
            enabled=True,
        )
        
        assert notifier.token == "test_token"
        assert notifier.chat_id == "123456"
        assert notifier.dry_run is True
        assert notifier.enabled is True
    
    def test_init_default_enabled(self):
        """Test that enabled defaults to True."""
        notifier = TelegramNotifier(
            token="test_token",
            chat_id="123456",
            dry_run=False,
        )
        
        assert notifier.enabled is True
    
    def test_init_disabled(self):
        """Test initialization with enabled=False."""
        notifier = TelegramNotifier(
            token="test_token",
            chat_id="123456",
            dry_run=True,
            enabled=False,
        )
        
        assert notifier.enabled is False


class TestMessageTruncation:
    """Tests for message truncation."""
    
    def test_truncate_short_message(self):
        """Test that short messages are not truncated."""
        notifier = TelegramNotifier(
            token="test",
            chat_id="123",
            dry_run=True,
        )
        
        short_message = "Hello, world!"
        result = notifier._truncate_message(short_message)
        
        assert result == short_message
    
    def test_truncate_exact_limit(self):
        """Test message at exactly the limit."""
        notifier = TelegramNotifier(
            token="test",
            chat_id="123",
            dry_run=True,
        )
        
        exact_message = "x" * 4096
        result = notifier._truncate_message(exact_message)
        
        assert result == exact_message
        assert len(result) == 4096
    
    def test_truncate_long_message(self):
        """Test that long messages are truncated with ellipsis."""
        notifier = TelegramNotifier(
            token="test",
            chat_id="123",
            dry_run=True,
        )
        
        long_message = "x" * 5000
        result = notifier._truncate_message(long_message)
        
        assert len(result) == 4096
        assert result.endswith("...")


class TestDeduplication:
    """Tests for message deduplication."""
    
    def test_message_hash_consistency(self):
        """Test that same message produces same hash."""
        notifier = TelegramNotifier(
            token="test",
            chat_id="123",
            dry_run=True,
        )
        
        message = "Test message"
        hash1 = notifier._get_message_hash(message)
        hash2 = notifier._get_message_hash(message)
        
        assert hash1 == hash2
    
    def test_different_messages_different_hash(self):
        """Test that different messages produce different hashes."""
        notifier = TelegramNotifier(
            token="test",
            chat_id="123",
            dry_run=True,
        )
        
        hash1 = notifier._get_message_hash("Message 1")
        hash2 = notifier._get_message_hash("Message 2")
        
        assert hash1 != hash2
    
    def test_is_duplicate_first_message(self):
        """Test that first message is not a duplicate."""
        notifier = TelegramNotifier(
            token="test",
            chat_id="123",
            dry_run=True,
        )
        
        assert notifier._is_duplicate("New message") is False
    
    def test_is_duplicate_after_recording(self):
        """Test that recorded message is detected as duplicate."""
        notifier = TelegramNotifier(
            token="test",
            chat_id="123",
            dry_run=True,
        )
        
        message = "Test message"
        notifier._record_message(message)
        
        assert notifier._is_duplicate(message) is True
    
    def test_different_message_not_duplicate(self):
        """Test that different message is not a duplicate."""
        notifier = TelegramNotifier(
            token="test",
            chat_id="123",
            dry_run=True,
        )
        
        notifier._record_message("Message 1")
        
        assert notifier._is_duplicate("Message 2") is False
    
    def test_dedup_cache_cleanup(self):
        """Test that old entries are cleaned from dedup cache."""
        notifier = TelegramNotifier(
            token="test",
            chat_id="123",
            dry_run=True,
        )
        
        # Add an old entry
        message = "Old message"
        message_hash = notifier._get_message_hash(message)
        notifier._dedup_cache[message_hash] = datetime.utcnow() - timedelta(minutes=10)
        
        # Cleanup should remove it
        notifier._cleanup_dedup_cache()
        
        assert message_hash not in notifier._dedup_cache


class TestDisabledMode:
    """Tests for disabled notifier behavior."""
    
    @pytest.mark.asyncio
    async def test_send_message_when_disabled(self):
        """Test that _send_message returns False when disabled."""
        notifier = TelegramNotifier(
            token="test",
            chat_id="123",
            dry_run=True,
            enabled=False,
        )
        
        result = await notifier._send_message("Test message")
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_no_http_request_when_disabled(self):
        """Test that no HTTP request is made when disabled."""
        notifier = TelegramNotifier(
            token="test",
            chat_id="123",
            dry_run=True,
            enabled=False,
        )
        
        with patch.object(notifier, '_get_session') as mock_session:
            await notifier._send_message("Test message")
            mock_session.assert_not_called()


class TestRetryLogic:
    """Tests for retry logic with mocked HTTP responses."""
    
    @staticmethod
    def _create_mock_response(status: int, json_data: dict | None = None):
        """Create a mock response that works with async context manager."""
        mock_response = MagicMock()
        mock_response.status = status
        if json_data is not None:
            mock_response.json = AsyncMock(return_value=json_data)
        return mock_response
    
    @staticmethod
    def _create_mock_context_manager(response):
        """Create a mock async context manager for session.post()."""
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=response)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        return mock_cm
    
    @pytest.mark.asyncio
    async def test_successful_send(self):
        """Test successful message send."""
        notifier = TelegramNotifier(
            token="test_token",
            chat_id="123456",
            dry_run=True,
            enabled=True,
        )
        
        mock_response = self._create_mock_response(200)
        mock_cm = self._create_mock_context_manager(mock_response)
        
        mock_session = MagicMock()
        mock_session.post.return_value = mock_cm
        
        with patch.object(notifier, '_get_session', AsyncMock(return_value=mock_session)):
            result = await notifier._send_message("Test message")
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_invalid_token_disables_notifier(self):
        """Test that 401 response disables the notifier."""
        notifier = TelegramNotifier(
            token="invalid_token",
            chat_id="123456",
            dry_run=True,
            enabled=True,
        )
        
        mock_response = self._create_mock_response(401)
        mock_cm = self._create_mock_context_manager(mock_response)
        
        mock_session = MagicMock()
        mock_session.post.return_value = mock_cm
        
        with patch.object(notifier, '_get_session', AsyncMock(return_value=mock_session)):
            result = await notifier._send_message("Test message")
        
        assert result is False
        assert notifier.enabled is False
    
    @pytest.mark.asyncio
    async def test_chat_not_found_disables_notifier(self):
        """Test that chat not found error disables the notifier."""
        notifier = TelegramNotifier(
            token="test_token",
            chat_id="invalid_chat",
            dry_run=True,
            enabled=True,
        )
        
        mock_response = self._create_mock_response(
            400,
            {"ok": False, "description": "Bad Request: chat not found"}
        )
        mock_cm = self._create_mock_context_manager(mock_response)
        
        mock_session = MagicMock()
        mock_session.post.return_value = mock_cm
        
        with patch.object(notifier, '_get_session', AsyncMock(return_value=mock_session)):
            result = await notifier._send_message("Test message")
        
        assert result is False
        assert notifier.enabled is False
    
    @pytest.mark.asyncio
    async def test_rate_limit_waits_and_retries(self):
        """Test that rate limit response waits and retries."""
        notifier = TelegramNotifier(
            token="test_token",
            chat_id="123456",
            dry_run=True,
            enabled=True,
        )
        
        # First response: rate limited, second: success
        mock_response_429 = self._create_mock_response(
            429,
            {"parameters": {"retry_after": 0.01}}
        )
        mock_response_200 = self._create_mock_response(200)
        
        mock_cm_429 = self._create_mock_context_manager(mock_response_429)
        mock_cm_200 = self._create_mock_context_manager(mock_response_200)
        
        mock_session = MagicMock()
        mock_session.post.side_effect = [mock_cm_429, mock_cm_200]
        
        with patch.object(notifier, '_get_session', AsyncMock(return_value=mock_session)):
            result = await notifier._send_message("Test message")
        
        assert result is True
        assert mock_session.post.call_count == 2
    
    @pytest.mark.asyncio
    async def test_network_error_retries(self):
        """Test that network errors trigger retries."""
        notifier = TelegramNotifier(
            token="test_token",
            chat_id="123456",
            dry_run=True,
            enabled=True,
        )
        
        # Override backoff for faster test
        notifier.INITIAL_BACKOFF_SECONDS = 0.01
        
        mock_response_200 = self._create_mock_response(200)
        mock_cm_200 = self._create_mock_context_manager(mock_response_200)
        
        # Simulate network errors by having post() raise aiohttp.ClientError
        import aiohttp
        
        call_count = [0]
        def post_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise aiohttp.ClientError("Network error")
            return mock_cm_200
        
        mock_session = MagicMock()
        mock_session.post.side_effect = post_side_effect
        
        with patch.object(notifier, '_get_session', AsyncMock(return_value=mock_session)):
            result = await notifier._send_message("Test message")
        
        assert result is True
        assert call_count[0] == 3
    
    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """Test that message fails after max retries."""
        notifier = TelegramNotifier(
            token="test_token",
            chat_id="123456",
            dry_run=True,
            enabled=True,
        )
        
        # Override backoff for faster test
        notifier.INITIAL_BACKOFF_SECONDS = 0.01
        
        # Simulate network errors by having post() raise aiohttp.ClientError
        import aiohttp
        
        mock_session = MagicMock()
        mock_session.post.side_effect = aiohttp.ClientError("Network error")
        
        with patch.object(notifier, '_get_session', AsyncMock(return_value=mock_session)):
            result = await notifier._send_message("Test message")
        
        assert result is False
        assert mock_session.post.call_count == 3  # MAX_RETRIES


class TestNotificationMethods:
    """Tests for high-level notification methods."""
    
    @pytest.mark.asyncio
    async def test_send_startup(self):
        """Test send_startup calls _send_message with formatted message."""
        notifier = TelegramNotifier(
            token="test_token",
            chat_id="123456",
            dry_run=True,
            enabled=True,
        )
        
        with patch.object(notifier, '_send_message', new_callable=AsyncMock) as mock_send:
            await notifier.send_startup(
                config_summary={
                    "bet_size": 10.0,
                    "hedge_size": 15.0,
                    "hedge_leverage": 3,
                    "max_daily_loss": 100.0,
                },
                timestamp=datetime(2024, 1, 15, 12, 0, 0),
            )
            
            mock_send.assert_called_once()
            message = mock_send.call_args[0][0]
            assert "DRY RUN" in message
            assert "Bot Started" in message
    
    @pytest.mark.asyncio
    async def test_send_shutdown(self):
        """Test send_shutdown calls _send_message with formatted message."""
        notifier = TelegramNotifier(
            token="test_token",
            chat_id="123456",
            dry_run=False,
            enabled=True,
        )
        
        with patch.object(notifier, '_send_message', new_callable=AsyncMock) as mock_send:
            await notifier.send_shutdown(
                reason="graceful",
                session_trades=5,
                session_pnl=25.50,
                timestamp=datetime(2024, 1, 15, 18, 0, 0),
            )
            
            mock_send.assert_called_once()
            message = mock_send.call_args[0][0]
            assert "LIVE" in message
            assert "Bot Shutdown" in message
    
    @pytest.mark.asyncio
    async def test_send_error(self):
        """Test send_error calls _send_message with formatted message."""
        notifier = TelegramNotifier(
            token="test_token",
            chat_id="123456",
            dry_run=True,
            enabled=True,
        )
        
        with patch.object(notifier, '_send_message', new_callable=AsyncMock) as mock_send:
            await notifier.send_error(
                error_type="API Error",
                exchange="binance",
                message="Connection timeout",
            )
            
            mock_send.assert_called_once()
            message = mock_send.call_args[0][0]
            assert "Error" in message
            assert "binance" in message


class TestClose:
    """Tests for session cleanup."""
    
    @pytest.mark.asyncio
    async def test_close_session(self):
        """Test that close() closes the aiohttp session."""
        notifier = TelegramNotifier(
            token="test_token",
            chat_id="123456",
            dry_run=True,
            enabled=True,
        )
        
        # Create a mock session
        mock_session = AsyncMock()
        mock_session.closed = False
        notifier._session = mock_session
        
        await notifier.close()
        
        mock_session.close.assert_called_once()
        assert notifier._session is None
    
    @pytest.mark.asyncio
    async def test_close_no_session(self):
        """Test that close() handles no session gracefully."""
        notifier = TelegramNotifier(
            token="test_token",
            chat_id="123456",
            dry_run=True,
            enabled=True,
        )
        
        # No session created yet
        await notifier.close()  # Should not raise
