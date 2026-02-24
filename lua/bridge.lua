-- reaper-mcp bridge: TCP socket server running inside REAPER
-- LuaSocket is bundled in lua/deps/ (Mavriq build for REAPER's Lua 5.4)

-- Set up package paths to find bundled LuaSocket
local info = debug.getinfo(1, 'S')
local script_dir = info.source:match[[^@?(.*[\/])[^\/]-$]]
local sep = package.config:sub(1, 1)
local deps_dir = script_dir .. "deps"

-- Detect platform and pick the right binary extension/name
local os_name = reaper.GetOS()
local ext = os_name:match('Win') and 'dll' or 'so'

-- On macOS/Linux, the release ships platform-specific .so files
-- We rename them at bundle time: core.dll (win), core_mac.so, core_linux.so
-- But we also keep core.dll/core.so as the default names
if not os_name:match('Win') then
    -- Check if we need to copy the platform-specific binary to core.so
    local core_path = deps_dir .. sep .. "socket" .. sep .. "core.so"
    local platform_suffix = os_name:match('OSX') and '_mac' or '_linux'
    local platform_path = deps_dir .. sep .. "socket" .. sep .. "core" .. platform_suffix .. ".so"

    -- If core.so doesn't exist but platform-specific one does, copy it
    local f = io.open(core_path, 'rb')
    if not f then
        local src = io.open(platform_path, 'rb')
        if src then
            local dst = io.open(core_path, 'wb')
            if dst then
                dst:write(src:read('*a'))
                dst:close()
            end
            src:close()
        end
    else
        f:close()
    end
end

-- Add bundled deps to Lua's search paths (before system paths)
package.cpath = deps_dir .. sep .. "?." .. ext .. ";"
             .. deps_dir .. sep .. "?" .. sep .. "?." .. ext .. ";"
             .. package.cpath
package.path  = deps_dir .. sep .. "?.lua;" .. package.path

local socket = require("socket")

-- ============================================================================
-- Configuration
-- ============================================================================

local PORT = tonumber(os.getenv("REAPER_MCP_PORT")) or 9500
local HOST = "127.0.0.1"
local MAX_MSG_SIZE = 10 * 1024 * 1024  -- 10MB max message

-- ============================================================================
-- JSON codec (minimal, no external deps)
-- ============================================================================

local json = {}

function json.encode(val)
    local t = type(val)
    if val == nil then return "null"
    elseif t == "boolean" then return val and "true" or "false"
    elseif t == "number" then
        if val ~= val then return "null" end  -- NaN
        if val == math.huge then return "1e999" end
        if val == -math.huge then return "-1e999" end
        return string.format("%.17g", val)
    elseif t == "string" then
        val = val:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n')
                 :gsub('\r', '\\r'):gsub('\t', '\\t')
        -- Escape control characters
        val = val:gsub('[\x00-\x1f]', function(c)
            return string.format('\\u%04x', string.byte(c))
        end)
        return '"' .. val .. '"'
    elseif t == "table" then
        -- Check if array
        local is_array = true
        local max_idx = 0
        for k, _ in pairs(val) do
            if type(k) ~= "number" or k ~= math.floor(k) or k < 1 then
                is_array = false
                break
            end
            if k > max_idx then max_idx = k end
        end
        if is_array and max_idx == #val then
            local parts = {}
            for i = 1, #val do
                parts[i] = json.encode(val[i])
            end
            return "[" .. table.concat(parts, ",") .. "]"
        else
            local parts = {}
            for k, v in pairs(val) do
                table.insert(parts, json.encode(tostring(k)) .. ":" .. json.encode(v))
            end
            return "{" .. table.concat(parts, ",") .. "}"
        end
    elseif t == "userdata" then
        return json.encode(tostring(val))
    else
        return "null"
    end
end

function json.decode(str)
    local pos = 1

    local function skip_ws()
        pos = str:match('^%s*()', pos)
    end

    local function parse_string()
        pos = pos + 1  -- skip opening "
        local parts = {}
        while pos <= #str do
            local c = str:sub(pos, pos)
            if c == '"' then
                pos = pos + 1
                return table.concat(parts)
            elseif c == '\\' then
                pos = pos + 1
                local esc = str:sub(pos, pos)
                if esc == 'n' then table.insert(parts, '\n')
                elseif esc == 'r' then table.insert(parts, '\r')
                elseif esc == 't' then table.insert(parts, '\t')
                elseif esc == '"' then table.insert(parts, '"')
                elseif esc == '\\' then table.insert(parts, '\\')
                elseif esc == '/' then table.insert(parts, '/')
                elseif esc == 'u' then
                    local hex = str:sub(pos + 1, pos + 4)
                    local code = tonumber(hex, 16)
                    if code then
                        if code < 128 then
                            table.insert(parts, string.char(code))
                        else
                            table.insert(parts, string.char(
                                0xC0 + math.floor(code / 64),
                                0x80 + (code % 64)
                            ))
                        end
                        pos = pos + 4
                    end
                end
                pos = pos + 1
            else
                table.insert(parts, c)
                pos = pos + 1
            end
        end
        error("Unterminated string")
    end

    local parse_value  -- forward declaration

    local function parse_array()
        pos = pos + 1  -- skip [
        local arr = {}
        skip_ws()
        if str:sub(pos, pos) == ']' then
            pos = pos + 1
            return arr
        end
        while true do
            skip_ws()
            table.insert(arr, parse_value())
            skip_ws()
            local c = str:sub(pos, pos)
            if c == ']' then
                pos = pos + 1
                return arr
            elseif c == ',' then
                pos = pos + 1
            else
                error("Expected ',' or ']' in array at pos " .. pos)
            end
        end
    end

    local function parse_object()
        pos = pos + 1  -- skip {
        local obj = {}
        skip_ws()
        if str:sub(pos, pos) == '}' then
            pos = pos + 1
            return obj
        end
        while true do
            skip_ws()
            if str:sub(pos, pos) ~= '"' then
                error("Expected string key at pos " .. pos)
            end
            local key = parse_string()
            skip_ws()
            if str:sub(pos, pos) ~= ':' then
                error("Expected ':' at pos " .. pos)
            end
            pos = pos + 1
            skip_ws()
            obj[key] = parse_value()
            skip_ws()
            local c = str:sub(pos, pos)
            if c == '}' then
                pos = pos + 1
                return obj
            elseif c == ',' then
                pos = pos + 1
            else
                error("Expected ',' or '}' in object at pos " .. pos)
            end
        end
    end

    parse_value = function()
        skip_ws()
        local c = str:sub(pos, pos)
        if c == '"' then return parse_string()
        elseif c == '{' then return parse_object()
        elseif c == '[' then return parse_array()
        elseif c == 't' then
            pos = pos + 4; return true
        elseif c == 'f' then
            pos = pos + 5; return false
        elseif c == 'n' then
            pos = pos + 4; return nil
        else
            local num_str = str:match('^-?%d+%.?%d*[eE]?[+-]?%d*', pos)
            if num_str then
                pos = pos + #num_str
                return tonumber(num_str)
            end
            error("Unexpected character '" .. c .. "' at pos " .. pos)
        end
    end

    local ok, result = pcall(parse_value)
    if ok then return result
    else return nil, result end
end

-- ============================================================================
-- Script execution engine
-- ============================================================================

local function execute_script(code, undo_label, timeout_ms)
    undo_label = undo_label or "AI Script"
    timeout_ms = timeout_ms or 120000
    local timeout_sec = timeout_ms / 1000.0

    -- Capture stdout
    local output = {}
    local old_print = print
    local old_msg = reaper.ShowConsoleMsg

    print = function(...)
        local parts = {}
        for i = 1, select('#', ...) do
            parts[i] = tostring(select(i, ...))
        end
        table.insert(output, table.concat(parts, "\t"))
    end

    reaper.ShowConsoleMsg = function(msg)
        table.insert(output, tostring(msg))
    end

    -- Compile
    local chunk, compile_err = load(code, "user_script")
    if not chunk then
        -- Restore
        print = old_print
        reaper.ShowConsoleMsg = old_msg

        -- Extract line number from compile error
        local line = tonumber(tostring(compile_err):match('%[string "user_script"%]:(%d+)'))
        local lines = {}
        for l in code:gmatch("[^\n]+") do table.insert(lines, l) end
        local context = {}
        if line then
            for i = math.max(1, line - 2), math.min(#lines, line + 2) do
                table.insert(context, string.format("%s %d: %s",
                    i == line and ">>>" or "   ", i, lines[i]))
            end
        end

        return {
            success = false,
            result = nil,
            stdout = table.concat(output, "\n"),
            error = {
                message = tostring(compile_err),
                line = line,
                traceback = nil,
                source_context = context
            },
            elapsed_ms = 0
        }
    end

    -- Set up timeout hook using debug.sethook
    local hook_start = reaper.time_precise()
    local hook_deadline = hook_start + timeout_sec

    local function timeout_hook()
        local now = reaper.time_precise()
        if now >= hook_deadline then
            local elapsed_sec = now - hook_start
            local result = reaper.MB(
                string.format("Script has been running for %.1f seconds. Kill it?", elapsed_sec),
                "Script Timeout", 4)  -- 4 = Yes/No
            if result == 6 then  -- 6 = Yes
                debug.sethook()  -- clear hook before erroring
                error("Script timed out after " .. string.format("%.1f", elapsed_sec) .. " seconds")
            else
                -- User chose No — reset deadline and continue
                hook_deadline = reaper.time_precise() + timeout_sec
            end
        end
    end

    -- Execute with undo block
    reaper.Undo_BeginBlock()
    reaper.PreventUIRefresh(1)

    -- Install hook: check every ~1M instructions
    debug.sethook(timeout_hook, "", 1000000)

    local start_time = reaper.time_precise()
    local ok, err_or_result = xpcall(chunk, function(e)
        return {
            message = tostring(e),
            traceback = debug.traceback(e, 2)
        }
    end)
    local elapsed = (reaper.time_precise() - start_time) * 1000

    -- Always clear the hook
    debug.sethook()

    reaper.PreventUIRefresh(-1)
    reaper.Undo_EndBlock(undo_label, -1)
    reaper.UpdateArrange()

    -- Restore
    print = old_print
    reaper.ShowConsoleMsg = old_msg

    if ok then
        return {
            success = true,
            result = err_or_result,
            stdout = table.concat(output, "\n"),
            error = nil,
            elapsed_ms = elapsed
        }
    else
        -- Extract line number from traceback
        local err_info = err_or_result
        local line = tonumber(tostring(err_info.message):match('%[string "user_script"%]:(%d+)'))
        local lines = {}
        for l in code:gmatch("[^\n]+") do table.insert(lines, l) end
        local context = {}
        if line then
            for i = math.max(1, line - 2), math.min(#lines, line + 2) do
                table.insert(context, string.format("%s %d: %s",
                    i == line and ">>>" or "   ", i, lines[i]))
            end
        end

        return {
            success = false,
            result = nil,
            stdout = table.concat(output, "\n"),
            error = {
                message = err_info.message,
                line = line,
                traceback = err_info.traceback,
                source_context = context
            },
            elapsed_ms = elapsed
        }
    end
end

-- ============================================================================
-- Built-in commands (not user scripts)
-- ============================================================================

local commands = {}

function commands.exec(params)
    return execute_script(params.code, params.undo_label, params.timeout_ms)
end

function commands.ping()
    return { pong = true, time = reaper.time_precise() }
end

function commands.startup(params)
    local action = params and params.action or "status"
    local resource = reaper.GetResourcePath()
    local sep = package.config:sub(1, 1)
    local scripts_dir = resource .. sep .. "Scripts"
    local startup_path = scripts_dir .. sep .. "__startup.lua"
    local bridge_path = script_dir .. "bridge.lua"
    local escaped = bridge_path:gsub("\\", "\\\\")
    local marker = "-- reaper-mcp bridge"
    local dofile_line = 'dofile("' .. escaped .. '")  ' .. marker

    -- Read existing file content (nil if doesn't exist)
    local function read_file()
        local f = io.open(startup_path, "r")
        if not f then return nil end
        local content = f:read("*a")
        f:close()
        return content
    end

    -- Check if our line is already present
    local function has_bridge_line(content)
        return content and content:find(marker, 1, true) ~= nil
    end

    if action == "status" then
        local content = read_file()
        return {
            enabled = has_bridge_line(content),
            startup_path = startup_path,
            bridge_path = bridge_path,
            content = content
        }
    elseif action == "enable" then
        local content = read_file()
        if has_bridge_line(content) then
            return {
                enabled = true,
                startup_path = startup_path,
                bridge_path = bridge_path,
                content = content,
                message = "Already enabled"
            }
        end
        -- Append our line to existing content (or create new file)
        local f, err = io.open(startup_path, "a")
        if not f then
            error("Cannot write startup file: " .. tostring(err))
        end
        if content and #content > 0 and not content:match("\n$") then
            f:write("\n")
        end
        f:write(dofile_line .. "\n")
        f:close()
        return {
            enabled = true,
            startup_path = startup_path,
            bridge_path = bridge_path,
            content = read_file()
        }
    elseif action == "disable" then
        local content = read_file()
        if not content then
            return {
                enabled = false,
                startup_path = startup_path,
                bridge_path = bridge_path
            }
        end
        -- Remove only our line(s), preserve everything else
        local lines = {}
        for line in (content .. "\n"):gmatch("(.-)\n") do
            if not line:find(marker, 1, true) then
                table.insert(lines, line)
            end
        end
        local new_content = table.concat(lines, "\n")
        -- Trim trailing whitespace
        new_content = new_content:gsub("%s+$", "")
        if #new_content > 0 then
            -- Other content remains — write it back
            local f, err = io.open(startup_path, "w")
            if not f then
                error("Cannot write startup file: " .. tostring(err))
            end
            f:write(new_content .. "\n")
            f:close()
        else
            -- File would be empty — just delete it
            os.remove(startup_path)
        end
        return {
            enabled = false,
            startup_path = startup_path,
            bridge_path = bridge_path,
            content = read_file()
        }
    else
        error("Unknown startup action: " .. tostring(action) .. ". Use 'status', 'enable', or 'disable'.")
    end
end

function commands.state()
    -- Full project state dump
    local state = {
        tracks = {},
        tempo = reaper.Master_GetTempo(),
        time_sig = {},
        cursor = reaper.GetCursorPosition(),
        play_state = reaper.GetPlayState(),  -- 0=stop, 1=play, 2=pause, 4=record
        project_name = "",
        project_path = "",
        markers = {},
        regions = {},
    }

    -- Time signature
    local ts_num, ts_den = reaper.TimeMap_GetTimeSigAtTime(0, 0)
    state.time_sig = { numerator = ts_num, denominator = ts_den }

    -- Project info
    local _, proj_name = reaper.GetProjectName(0)
    local proj_path = reaper.GetProjectPath()
    state.project_name = proj_name
    state.project_path = proj_path

    -- Tracks
    local num_tracks = reaper.CountTracks(0)
    for i = 0, num_tracks - 1 do
        local track = reaper.GetTrack(0, i)
        local _, name = reaper.GetTrackName(track)
        local vol = reaper.GetMediaTrackInfo_Value(track, "D_VOL")
        local pan = reaper.GetMediaTrackInfo_Value(track, "D_PAN")
        local mute = reaper.GetMediaTrackInfo_Value(track, "B_MUTE")
        local solo = reaper.GetMediaTrackInfo_Value(track, "I_SOLO")
        local armed = reaper.GetMediaTrackInfo_Value(track, "I_RECARM")
        local num_items = reaper.CountTrackMediaItems(track)
        local num_fx = reaper.TrackFX_GetCount(track)

        local fx_list = {}
        for fx = 0, num_fx - 1 do
            local _, fx_name = reaper.TrackFX_GetFXName(track, fx)
            local enabled = reaper.TrackFX_GetEnabled(track, fx)
            table.insert(fx_list, { name = fx_name, enabled = enabled, index = fx })
        end

        local items_info = {}
        for item_idx = 0, num_items - 1 do
            local item = reaper.GetTrackMediaItem(track, item_idx)
            local pos = reaper.GetMediaItemInfo_Value(item, "D_POSITION")
            local len = reaper.GetMediaItemInfo_Value(item, "D_LENGTH")
            local take = reaper.GetActiveTake(item)
            local item_info = {
                position = pos,
                length = len,
                is_midi = false,
                note_count = 0
            }
            if take then
                item_info.is_midi = reaper.TakeIsMIDI(take)
                if item_info.is_midi then
                    local _, note_count = reaper.MIDI_CountEvts(take)
                    item_info.note_count = note_count
                end
            end
            table.insert(items_info, item_info)
        end

        local db = 20 * math.log(vol, 10)

        table.insert(state.tracks, {
            index = i,
            name = name,
            volume_db = math.floor(db * 10 + 0.5) / 10,
            volume_linear = vol,
            pan = pan,
            mute = mute == 1,
            solo = solo > 0,
            armed = armed == 1,
            num_items = num_items,
            items = items_info,
            fx = fx_list,
        })
    end

    -- Markers and regions
    local num_markers = reaper.CountProjectMarkers(0)
    for i = 0, num_markers - 1 do
        local _, is_region, pos, region_end, name, idx = reaper.EnumProjectMarkers(i)
        if is_region then
            table.insert(state.regions, {
                index = idx, name = name, start = pos, ["end"] = region_end
            })
        else
            table.insert(state.markers, {
                index = idx, name = name, position = pos
            })
        end
    end

    return state
end

function commands.list_api(params)
    local filter = params and params.filter and params.filter:lower() or nil
    local funcs = {}
    for k, v in pairs(reaper) do
        if type(v) == "function" then
            if not filter or k:lower():find(filter, 1, true) then
                table.insert(funcs, k)
            end
        end
    end
    table.sort(funcs)
    return { functions = funcs, count = #funcs }
end

-- ============================================================================
-- Socket server
-- ============================================================================

local server = nil
local client = nil
local recv_buffer = ""

local function start_server()
    local err
    server, err = socket.bind(HOST, PORT)
    if not server then
        reaper.ShowConsoleMsg("[reaper-mcp] ERROR: Could not bind to " .. HOST .. ":" .. PORT .. " — " .. tostring(err) .. "\n")
        reaper.ShowConsoleMsg("[reaper-mcp] Is something else using port " .. PORT .. "? Set REAPER_MCP_PORT env var to use a different port.\n")
        return false
    end
    server:settimeout(0)  -- non-blocking
    reaper.ShowConsoleMsg("[reaper-mcp] Listening on " .. HOST .. ":" .. PORT .. "\n")
    return true
end

local function send_response(response)
    if not client then return end
    local data = json.encode(response) .. "\n"
    local ok, err = client:send(data)
    if not ok then
        reaper.ShowConsoleMsg("[reaper-mcp] Send error: " .. tostring(err) .. "\n")
        client:close()
        client = nil
    end
end

local function handle_message(msg)
    local request, parse_err = json.decode(msg)
    if not request then
        return { error = { message = "JSON parse error: " .. tostring(parse_err) }, id = nil }
    end

    local method = request.method
    local params = request.params or {}
    local id = request.id

    local response = { id = id }

    local handler = commands[method]
    if handler then
        local ok, result = pcall(handler, params)
        if ok then
            response.result = result
        else
            response.error = { message = "Internal error: " .. tostring(result) }
        end
    else
        response.error = { message = "Unknown method: " .. tostring(method) }
    end

    return response
end

local function poll()
    -- Accept new connections
    if server and not client then
        local new_client, err = server:accept()
        if new_client then
            new_client:settimeout(0)
            client = new_client
            recv_buffer = ""
            reaper.ShowConsoleMsg("[reaper-mcp] Client connected\n")
        end
    end

    -- Read from client
    if client then
        local data, err, partial = client:receive(8192)
        local received = data or partial

        if received and #received > 0 then
            recv_buffer = recv_buffer .. received

            -- Process complete messages (newline-delimited)
            while true do
                local nl = recv_buffer:find("\n")
                if not nl then break end

                local msg = recv_buffer:sub(1, nl - 1)
                recv_buffer = recv_buffer:sub(nl + 1)

                if #msg > 0 then
                    local response = handle_message(msg)
                    send_response(response)
                end
            end

            -- Safety: prevent buffer overflow
            if #recv_buffer > MAX_MSG_SIZE then
                reaper.ShowConsoleMsg("[reaper-mcp] Buffer overflow, resetting\n")
                recv_buffer = ""
                send_response({ error = { message = "Message too large" }, id = nil })
            end
        end

        if err == "closed" then
            reaper.ShowConsoleMsg("[reaper-mcp] Client disconnected\n")
            client:close()
            client = nil
            recv_buffer = ""
        end
    end

    reaper.defer(poll)
end

-- ============================================================================
-- Startup
-- ============================================================================

local function main()
    reaper.ShowConsoleMsg("\n")
    reaper.ShowConsoleMsg("===========================================\n")
    reaper.ShowConsoleMsg("  reaper-mcp bridge v0.1.0\n")
    reaper.ShowConsoleMsg("===========================================\n")

    if start_server() then
        poll()
    end
end

main()
