-- Verify LuaSocket is available (bundled or installed)
-- Run this script in REAPER to check

-- Try bundled deps first
local info = debug.getinfo(1, 'S')
local script_dir = info.source:match[[^@?(.*[\/])[^\/]-$]]
local sep = package.config:sub(1, 1)
local deps_dir = script_dir .. "deps"
local ext = reaper.GetOS():match('Win') and 'dll' or 'so'

package.cpath = deps_dir .. sep .. "?." .. ext .. ";"
             .. deps_dir .. sep .. "?" .. sep .. "?." .. ext .. ";"
             .. package.cpath
package.path  = deps_dir .. sep .. "?.lua;" .. package.path

local ok, socket = pcall(require, "socket")
if ok then
    reaper.ShowConsoleMsg("[reaper-mcp] LuaSocket is available!\n")
    reaper.ShowConsoleMsg("[reaper-mcp] Version: " .. (socket._VERSION or "unknown") .. "\n")
    reaper.ShowConsoleMsg("[reaper-mcp] You're good to go. Load bridge.lua to start the MCP server.\n")
else
    reaper.ShowConsoleMsg("[reaper-mcp] ERROR: LuaSocket not found.\n\n")
    reaper.ShowConsoleMsg("Error: " .. tostring(socket) .. "\n\n")
    reaper.ShowConsoleMsg("The bundled LuaSocket binaries should be in:\n")
    reaper.ShowConsoleMsg("  " .. deps_dir .. sep .. "socket.lua\n")
    reaper.ShowConsoleMsg("  " .. deps_dir .. sep .. "socket" .. sep .. "core." .. ext .. "\n\n")
    reaper.ShowConsoleMsg("If files are missing, re-download or reinstall reaper-mcp.\n\n")
    reaper.ShowConsoleMsg("Alternative: install via ReaPack:\n")
    reaper.ShowConsoleMsg("  1. Extensions > ReaPack > Import repositories\n")
    reaper.ShowConsoleMsg("  2. Add: https://github.com/mavriq-dev/public-reascripts/raw/master/index.xml\n")
    reaper.ShowConsoleMsg("  3. Extensions > ReaPack > Browse packages\n")
    reaper.ShowConsoleMsg("  4. Search for 'sockmonkey' and install\n")
    reaper.ShowConsoleMsg("  5. Restart REAPER\n")
end
