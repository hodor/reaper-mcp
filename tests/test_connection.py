"""Tests for server/connection.py"""

import pytest
from server.connection import ReaperConnection, ConnectionError


class TestReaperConnection:
    def test_default_port(self):
        conn = ReaperConnection()
        assert conn.port == 9500
        assert conn.host == "127.0.0.1"
        assert not conn.connected

    def test_custom_port(self):
        conn = ReaperConnection(port=9999)
        assert conn.port == 9999

    @pytest.mark.asyncio
    async def test_connect_fails_no_server(self):
        conn = ReaperConnection(port=19999)  # unlikely to be in use
        with pytest.raises(ConnectionError, match="Cannot connect"):
            await conn.connect()
