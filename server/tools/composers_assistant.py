"""Composer's Assistant tools: install/deploy to REAPER and manage nn_server."""

import asyncio
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP
from server.connection import get_connection, ConnectionError

logger = logging.getLogger(__name__)

# Vendored Composer's Assistant root
CA_ROOT = Path(__file__).resolve().parent.parent.parent / "composers_assistant"
CA_SCRIPTS = CA_ROOT / "scripts"
CA_EFFECTS = CA_ROOT / "effects"
CA_MODELS = CA_ROOT / "models"

# Subprocess handle for nn_server
_nn_server_process: Optional[subprocess.Popen] = None


def _find_python() -> str:
    """Find the Python executable, preferring the current venv."""
    # If running in a venv, use its python
    venv_python = Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin") / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def register(mcp: FastMCP):

    @mcp.tool()
    async def setup_composers_assistant(action: str = "status") -> str:
        """Install, uninstall, or check status of Composer's Assistant in REAPER.

        Copies scripts and effects to REAPER's resource path so they appear
        in the Actions list and FX browser. Registers the 3 action scripts.

        Args:
            action: "install" to deploy files and register actions,
                    "uninstall" to remove deployed files,
                    "status" to check current state
        """
        if action not in ("install", "uninstall", "status"):
            return f"Unknown action: {action}. Use 'install', 'uninstall', or 'status'."

        # Verify vendored files exist
        if not CA_SCRIPTS.exists():
            return (
                f"Composer's Assistant scripts not found at {CA_SCRIPTS}. "
                "Make sure the vendored files are present."
            )

        # Get REAPER resource path via Lua
        conn = get_connection()
        try:
            result = await conn.execute(
                'print(reaper.GetResourcePath())'
            )
        except ConnectionError as e:
            return f"Connection error: {e}. Is REAPER running with the bridge loaded?"

        resource_path = result.get("stdout", "").strip()
        if not resource_path:
            return "Could not determine REAPER resource path."

        resource_path = Path(resource_path)
        dest_scripts = resource_path / "Scripts" / "composers_assistant_v2"
        dest_effects = resource_path / "Effects" / "composers_assistant_v2"

        action_scripts = [
            "REAPER_replace_selected_midi_items_in_time_selection.py",
            "REAPER_replace_selected_midi_items_in_time_selection_no_rep.py",
            "REAPER_replace_selected_midi_items_in_time_selection_with_variation.py",
        ]

        if action == "status":
            parts = []

            # Check deployed files
            scripts_installed = dest_scripts.exists() and any(dest_scripts.iterdir())
            effects_installed = dest_effects.exists() and any(dest_effects.iterdir())
            parts.append(f"Scripts deployed: {'Yes' if scripts_installed else 'No'}")
            parts.append(f"Effects deployed: {'Yes' if effects_installed else 'No'}")
            parts.append(f"Scripts path: {dest_scripts}")
            parts.append(f"Effects path: {dest_effects}")

            # Check models
            models_present = CA_MODELS.exists() and any(CA_MODELS.iterdir())
            parts.append(f"Models downloaded: {'Yes' if models_present else 'No'}")
            if not models_present:
                parts.append(f"  Download models from the Composer's Assistant GitHub releases")
                parts.append(f"  and extract into: {CA_MODELS}")

            # Check nn_server
            if _nn_server_process and _nn_server_process.poll() is None:
                parts.append(f"nn_server: Running (PID {_nn_server_process.pid})")
            else:
                parts.append("nn_server: Not running")

            return "\n".join(parts)

        elif action == "install":
            parts = []

            # Copy scripts
            dest_scripts.mkdir(parents=True, exist_ok=True)
            script_count = 0
            for f in CA_SCRIPTS.iterdir():
                if f.is_file():
                    shutil.copy2(f, dest_scripts / f.name)
                    script_count += 1
            parts.append(f"Copied {script_count} script files to {dest_scripts}")

            # Copy effects
            dest_effects.mkdir(parents=True, exist_ok=True)
            effect_count = 0
            for f in CA_EFFECTS.iterdir():
                if f.is_file():
                    shutil.copy2(f, dest_effects / f.name)
                    effect_count += 1
            parts.append(f"Copied {effect_count} effect files to {dest_effects}")

            # Register action scripts in REAPER
            for script_name in action_scripts:
                script_path = dest_scripts / script_name
                if script_path.exists():
                    # Escape backslashes for Lua string
                    lua_path = str(script_path).replace("\\", "/")
                    lua_code = (
                        f'local path = "{lua_path}"\n'
                        f'local id = reaper.AddRemoveReaScript(true, 0, path, true)\n'
                        f'print("Registered: " .. path .. " (action id: " .. tostring(id) .. ")")'
                    )
                    try:
                        reg_result = await conn.execute(lua_code)
                        stdout = reg_result.get("stdout", "").strip()
                        if stdout:
                            parts.append(stdout)
                    except ConnectionError:
                        parts.append(f"Warning: Could not register {script_name}")

            parts.append("")
            parts.append("Installation complete!")
            parts.append("Next steps:")
            parts.append("1. Add 'JS: Global Options for Composer's Assistant v2' to Monitor FX")
            parts.append("2. Download model weights and extract to: " + str(CA_MODELS))
            parts.append("3. Start the nn_server before generating")

            return "\n".join(parts)

        elif action == "uninstall":
            parts = []

            # Unregister action scripts first
            for script_name in action_scripts:
                script_path = dest_scripts / script_name
                if script_path.exists():
                    lua_path = str(script_path).replace("\\", "/")
                    lua_code = (
                        f'local path = "{lua_path}"\n'
                        f'local id = reaper.AddRemoveReaScript(false, 0, path, true)\n'
                        f'print("Unregistered: " .. path)'
                    )
                    try:
                        await conn.execute(lua_code)
                        parts.append(f"Unregistered {script_name}")
                    except ConnectionError:
                        parts.append(f"Warning: Could not unregister {script_name}")

            # Remove deployed files
            if dest_scripts.exists():
                shutil.rmtree(dest_scripts)
                parts.append(f"Removed {dest_scripts}")
            if dest_effects.exists():
                shutil.rmtree(dest_effects)
                parts.append(f"Removed {dest_effects}")

            parts.append("Uninstallation complete.")
            return "\n".join(parts)

    @mcp.tool()
    async def composers_assistant_server(action: str = "status") -> str:
        """Manage the Composer's Assistant neural network server.

        The nn_server must be running for MIDI generation to work.
        It loads a T5 transformer model and listens for XML-RPC requests.

        Args:
            action: "start" to launch the nn_server,
                    "stop" to shut it down,
                    "status" to check if it's running
        """
        global _nn_server_process

        if action not in ("start", "stop", "status"):
            return f"Unknown action: {action}. Use 'start', 'stop', or 'status'."

        nn_server_script = CA_SCRIPTS / "composers_assistant_nn_server.py"

        if action == "status":
            if _nn_server_process and _nn_server_process.poll() is None:
                return f"nn_server: Running (PID {_nn_server_process.pid})"
            else:
                if _nn_server_process:
                    rc = _nn_server_process.returncode
                    _nn_server_process = None
                    return f"nn_server: Stopped (exit code {rc})"
                return "nn_server: Not running"

        elif action == "start":
            # Check if already running
            if _nn_server_process and _nn_server_process.poll() is None:
                return f"nn_server: Already running (PID {_nn_server_process.pid})"

            # Verify script exists
            if not nn_server_script.exists():
                return f"nn_server script not found at {nn_server_script}"

            # Verify models exist
            if not CA_MODELS.exists() or not any(CA_MODELS.iterdir()):
                return (
                    "Models not found. Download model weights from the "
                    "Composer's Assistant GitHub releases page and extract "
                    f"into: {CA_MODELS}"
                )

            python = _find_python()
            try:
                _nn_server_process = subprocess.Popen(
                    [python, str(nn_server_script)],
                    cwd=str(CA_SCRIPTS),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                )
                # Give it a moment to start or fail
                await asyncio.sleep(2)

                if _nn_server_process.poll() is not None:
                    output = _nn_server_process.stdout.read().decode(errors="replace") if _nn_server_process.stdout else ""
                    rc = _nn_server_process.returncode
                    _nn_server_process = None
                    return f"nn_server failed to start (exit code {rc}).\n{output}"

                return (
                    f"nn_server started (PID {_nn_server_process.pid}).\n"
                    "Loading model weights — this may take a minute.\n"
                    "The server will be ready when it prints 'NN server running'."
                )
            except FileNotFoundError:
                return f"Python not found at {python}. Check your environment."
            except Exception as e:
                return f"Failed to start nn_server: {e}"

        elif action == "stop":
            if not _nn_server_process or _nn_server_process.poll() is not None:
                _nn_server_process = None
                return "nn_server: Not running"

            pid = _nn_server_process.pid
            _nn_server_process.terminate()
            try:
                _nn_server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _nn_server_process.kill()
                _nn_server_process.wait(timeout=5)

            _nn_server_process = None
            return f"nn_server stopped (was PID {pid})"
