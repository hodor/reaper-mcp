"""TCP socket connection to REAPER's Lua bridge."""

import asyncio
import json
import os
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_PORT = 9500
CONNECT_TIMEOUT = 5.0
REQUEST_TIMEOUT = 10.0
RECONNECT_DELAY = 1.0
RECONNECT_MAX_DELAY = 10.0


class ConnectionError(Exception):
    """Failed to connect or communicate with REAPER."""
    pass


class ReaperConnection:
    """Async TCP client for communicating with REAPER's Lua bridge."""

    def __init__(self, host: str = "127.0.0.1", port: Optional[int] = None):
        self.host = host
        self.port = port or int(os.getenv("REAPER_MCP_PORT", str(DEFAULT_PORT)))
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._request_id = 0
        self._lock = asyncio.Lock()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected and self._writer is not None

    async def connect(self) -> None:
        """Connect to REAPER. Raises ConnectionError if it fails."""
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=CONNECT_TIMEOUT
            )
            self._connected = True
            logger.info(f"Connected to REAPER at {self.host}:{self.port}")
        except (OSError, asyncio.TimeoutError) as e:
            self._connected = False
            raise ConnectionError(
                f"Cannot connect to REAPER at {self.host}:{self.port}. "
                f"Is REAPER running with the bridge script loaded? Error: {e}"
            ) from e

    async def disconnect(self) -> None:
        """Close the connection."""
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._writer = None
        self._reader = None
        self._connected = False

    async def ensure_connected(self) -> None:
        """Connect if not already connected."""
        if not self.connected:
            await self.connect()

    async def request(self, method: str, params: Optional[dict] = None,
                      timeout: Optional[float] = None) -> Any:
        """Send a request and wait for the response.

        Returns the result on success, raises on error.
        """
        await self.ensure_connected()

        self._request_id += 1
        request_id = self._request_id
        timeout = timeout or REQUEST_TIMEOUT

        msg = {
            "method": method,
            "params": params or {},
            "id": request_id
        }

        async with self._lock:
            try:
                data = json.dumps(msg) + "\n"
                self._writer.write(data.encode("utf-8"))
                await self._writer.drain()

                line = await asyncio.wait_for(
                    self._reader.readline(),
                    timeout=timeout
                )

                if not line:
                    self._connected = False
                    raise ConnectionError("Connection closed by REAPER")

                response = json.loads(line.decode("utf-8"))

                if "error" in response and response["error"]:
                    error = response["error"]
                    if isinstance(error, dict):
                        raise ConnectionError(error.get("message", str(error)))
                    raise ConnectionError(str(error))

                return response.get("result")

            except asyncio.TimeoutError:
                raise ConnectionError(
                    f"Request timed out after {timeout}s. "
                    f"Method: {method}"
                )
            except (OSError, json.JSONDecodeError) as e:
                self._connected = False
                raise ConnectionError(f"Communication error: {e}") from e

    async def ping(self) -> bool:
        """Check if REAPER is responsive."""
        try:
            result = await self.request("ping", timeout=2.0)
            return result is not None and result.get("pong") is True
        except Exception:
            return False

    async def execute(self, code: str, undo_label: Optional[str] = None,
                      timeout_ms: Optional[int] = None) -> dict:
        """Execute a Lua script in REAPER.

        Args:
            code: Lua source code to execute
            undo_label: Label for the undo history entry
            timeout_ms: Lua-side script timeout in milliseconds (default: 10000).
                Passed to the Lua bridge for debug.sethook-based timeout protection.
                Python socket timeout is set to this + 30s buffer for dialog interaction.

        Returns dict with: success, result, stdout, error, elapsed_ms
        """
        params = {"code": code}
        if undo_label:
            params["undo_label"] = undo_label
        if timeout_ms is not None:
            params["timeout_ms"] = timeout_ms

        # Socket timeout = script timeout + 30s buffer for user dialog interaction
        script_timeout_sec = (timeout_ms or 120000) / 1000.0
        socket_timeout = script_timeout_sec + 30.0

        return await self.request("exec", params, timeout=socket_timeout)

    async def startup(self, action: str = "status") -> dict:
        """Manage REAPER startup configuration for the MCP bridge."""
        return await self.request("startup", {"action": action})

    async def get_state(self) -> dict:
        """Get full project state from REAPER."""
        return await self.request("state")

    async def list_api(self, filter: Optional[str] = None) -> dict:
        """List available ReaScript API functions."""
        params = {}
        if filter:
            params["filter"] = filter
        return await self.request("list_api", params)


# Singleton
_connection: Optional[ReaperConnection] = None


def get_connection() -> ReaperConnection:
    """Get or create the singleton connection."""
    global _connection
    if _connection is None:
        _connection = ReaperConnection()
    return _connection
