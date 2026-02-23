"""Script analytics tools: history, common scripts."""

import time
from mcp.server.fastmcp import FastMCP
from server.script_tracker import get_tracker


def register(mcp: FastMCP):

    @mcp.tool()
    async def get_script_history(limit: int = 20) -> str:
        """Show recent script executions with timing and error info.

        Args:
            limit: Number of recent runs to show (default 20)
        """
        tracker = get_tracker()
        runs = tracker.get_history(limit)
        stats = tracker.get_stats()

        if not runs:
            return "No scripts have been executed yet."

        lines = [
            f"Script history ({stats['total_runs']} total runs, "
            f"{stats['total_unique_scripts']} unique scripts, "
            f"{stats['error_rate']:.0%} error rate)\n"
        ]

        for run in runs:
            status = "OK" if run.success else "ERR"
            ago = _format_ago(time.time() - run.timestamp)
            line = f"  [{status}] {run.elapsed_ms:.0f}ms | {ago} ago | {run.hash[:12]}"
            if run.error:
                line += f" | {run.error[:60]}"
            lines.append(line)

        return "\n".join(lines)

    @mcp.tool()
    async def get_common_scripts(min_runs: int = 2, limit: int = 10) -> str:
        """Show scripts that have been run multiple times.

        These are candidates for becoming dedicated MCP tools.

        Args:
            min_runs: Minimum run count to include (default 2)
            limit: Maximum results (default 10)
        """
        tracker = get_tracker()
        scripts = tracker.get_common_scripts(min_runs=min_runs, limit=limit)

        if not scripts:
            return f"No scripts have been run {min_runs}+ times yet."

        lines = [f"Scripts run {min_runs}+ times ({len(scripts)} found):\n"]

        for s in scripts:
            code_preview = s.code[:100].replace("\n", " ")
            if len(s.code) > 100:
                code_preview += "..."
            lines.append(f"  [{s.run_count}x] avg {s.avg_elapsed_ms:.0f}ms | {s.error_rate:.0%} errors")
            lines.append(f"    {code_preview}")
            lines.append(f"    hash: {s.hash[:16]}")
            lines.append("")

        return "\n".join(lines)


def _format_ago(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds/60:.0f}m"
    if seconds < 86400:
        return f"{seconds/3600:.1f}h"
    return f"{seconds/86400:.1f}d"
