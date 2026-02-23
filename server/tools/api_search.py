"""API documentation search tools."""

from typing import Optional
from mcp.server.fastmcp import FastMCP
from server.api_index import get_api_index
from server.connection import get_connection, ConnectionError


def register(mcp: FastMCP):

    @mcp.tool()
    async def search_api(query: str, limit: int = 15,
                         available_only: bool = False) -> str:
        """Search the REAPER ReaScript API documentation.

        Find functions by name, description, or category. Use this before writing
        scripts to find the right API functions.

        Args:
            query: Search terms (e.g., "get track name", "MIDI insert note", "FX parameter")
            limit: Maximum results to return (default 15)
            available_only: Only show functions confirmed available on this REAPER install
        """
        index = get_api_index()

        # Build index on first use if needed
        if not index.is_indexed:
            count = index.build_index()
            if count == 0:
                return (
                    "API docs not indexed yet. Place reascripthelp.html in the data/ "
                    "directory, or generate it from REAPER (Help > ReaScript documentation) "
                    "and provide the path."
                )

        results = index.search(query, limit=limit, available_only=available_only)

        if not results:
            return f"No API functions found matching '{query}'"

        lines = [f"Found {len(results)} functions matching '{query}':\n"]
        for func in results:
            lines.append(f"reaper.{func.name}")
            if func.signature:
                lines.append(f"  Signature: {func.signature}")
            if func.description:
                desc = func.description[:200]
                if len(func.description) > 200:
                    desc += "..."
                lines.append(f"  {desc}")
            lines.append(f"  Category: {func.category}")
            lines.append("")

        return "\n".join(lines)

    @mcp.tool()
    async def list_available_api(filter: Optional[str] = None) -> str:
        """List ReaScript API functions available on this REAPER installation.

        Discovers functions at runtime by querying REAPER directly.
        This includes all installed extensions (SWS, JS, etc.).

        Args:
            filter: Optional prefix filter (e.g., "MIDI", "FX", "Track", "CF_")
        """
        conn = get_connection()

        try:
            result = await conn.list_api(filter)
        except ConnectionError as e:
            return f"Error: {e}"

        funcs = result.get("functions", [])
        count = result.get("count", len(funcs))

        if not funcs:
            msg = "No functions found"
            if filter:
                msg += f" matching '{filter}'"
            return msg

        # Group by inferred prefix
        header = f"{count} functions"
        if filter:
            header += f" matching '{filter}'"

        # Show up to 100, summarize the rest
        if count <= 100:
            return f"{header}:\n" + "\n".join(f"  reaper.{f}" for f in funcs)
        else:
            shown = funcs[:100]
            return (
                f"{header} (showing first 100):\n"
                + "\n".join(f"  reaper.{f}" for f in shown)
                + f"\n\n... and {count - 100} more"
            )
