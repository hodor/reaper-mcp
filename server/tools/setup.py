"""Setup tools: manage REAPER startup configuration."""

from mcp.server.fastmcp import FastMCP
from server.connection import get_connection, ConnectionError


def register(mcp: FastMCP):

    @mcp.tool()
    async def manage_startup(action: str = "status") -> str:
        """Manage the REAPER startup script for the MCP bridge.

        Checks whether REAPER is configured to auto-load the bridge on startup,
        and can enable or disable it. The bridge's own path is resolved
        automatically at runtime.

        Args:
            action: "status" to check current state,
                    "enable" to create/update __startup.lua,
                    "disable" to remove it
        """
        conn = get_connection()

        try:
            result = await conn.startup(action)
        except ConnectionError as e:
            return f"Connection error: {e}"

        parts = []
        enabled = result.get("enabled")
        content = result.get("content")
        startup_path = result.get("startup_path", "unknown")

        if enabled:
            parts.append("Startup: ENABLED")
        else:
            parts.append("Startup: DISABLED")

        parts.append(f"Bridge: {result.get('bridge_path', 'unknown')}")
        parts.append(f"Startup file: {startup_path}")

        if result.get("message"):
            parts.append(result["message"])

        if action == "status":
            if content:
                has_other = any(
                    line.strip() and "reaper-mcp bridge" not in line
                    for line in content.splitlines()
                )
                if has_other:
                    parts.append(
                        f"File contains other startup code. "
                        f"Review it at: {startup_path}"
                    )
            elif not enabled:
                parts.append(
                    "No startup file exists. Use action='enable' to create one."
                )
        elif action == "enable" and not result.get("message"):
            parts.append("Bridge line added. REAPER will auto-load it on next launch.")
        elif action == "disable":
            if content:
                parts.append("Bridge line removed. Other startup content preserved.")
            else:
                parts.append("Bridge line removed.")

        return "\n".join(parts)
