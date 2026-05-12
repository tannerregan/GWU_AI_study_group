# Fix: mcp-stata "Connection closed" Error on Windows

## Symptom

Running Stata via the **Stata Workbench** VS Code extension fails with:

```
Failed to connect to mcp-stata: MCP error -32000: Connection closed
```

## Root Cause

When the Stata Workbench extension updates (e.g., from v0.24.4 to v1.1.1+), the VS Code MCP config at `%APPDATA%\Code\User\mcp.json` still references the old version's bundled `uv.exe`, which no longer exists. The extension detects that the configured command is missing and silently falls back to the system `uvx` — but without the `--python 3.11` flag that was in the old config. The system `uvx` then uses Python 3.14 (or another newer version), which is incompatible with Stata 18's compiled `sfi` C extension. The pre-flight check fails, the result is cached as `working: false` in `~/.mcp-stata-discovery-cache.json`, and subsequent attempts immediately return the cached failure.

## Fix

Three steps, all required:

### 1. Update the MCP config

Open `%APPDATA%\Code\User\mcp.json` and replace the `mcp_stata` server entry so it uses the system `uvx` with `--python 3.11` explicitly:

```json
{
  "servers": {
    "mcp_stata": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "--python",
        "3.11",
        "--refresh",
        "--refresh-package",
        "mcp-stata",
        "--from",
        "mcp-stata@latest",
        "mcp-stata"
      ],
      "env": {
        "STATA_PATH": "C:\\Program Files\\Stata18",
        "KMP_DUPLICATE_LIB_OK": "TRUE",
        "MCP_STATA_ALLOWED_ROOTS": "C:\\Users\\tanner_regan"
      }
    }
  }
}
```

Key points:
- `command` must be `"uvx"` (not a path to a bundled uv.exe from an old extension version)
- `--python 3.11` is required — Stata 18's `sfi` extension is not compatible with Python 3.13+
- `STATA_PATH` should be the **directory** (`C:\Program Files\Stata18`), not the exe
- `KMP_DUPLICATE_LIB_OK` suppresses a potential OpenMP duplicate-library crash
- `MCP_STATA_ALLOWED_ROOTS` tells mcp-stata which paths outside the workspace are allowed in `use` commands. mcp-stata v3.3+ blocks file paths that are not under the workspace, system temp, or this list. Set it to your user home directory (`C:\Users\<username>`) to allow Box Drive, OneDrive, and any other paths under your profile.

Verify that Python 3.11 is available to uv:

```powershell
uv python list
# Should show: cpython-3.11.x-windows-x86_64-none  (installed, not just "download available")
```

If not installed, run: `uv python install 3.11`

### 2. Clear the discovery cache

mcp-stata caches the failed pre-flight result for 24 hours. Clear it so the next launch re-runs verification:

```powershell
'{}' | Out-File -FilePath "$env:USERPROFILE\.mcp-stata-discovery-cache.json" -Encoding utf8
```

### 3. Restart VS Code

Fully close and reopen VS Code. The Stata Workbench connection should work after restart.

## Notes for Claude

If a colleague runs into this error and asks Claude to fix it:

1. Check `%APPDATA%\Code\User\mcp.json` — if the `command` field points to a path inside a `.vscode\extensions\tmonk.stata-workbench-*` folder, that path is stale. Replace it with the config above.
2. Clear the discovery cache with the PowerShell command above.
3. Tell the user to restart VS Code.

The root cause is always a stale `command` path after an extension update causing fallback to a newer Python that Stata 18 does not support. The fix is updating the MCP config to pin `--python 3.11`.

## Issue 2: `use` on Box/OneDrive paths gives no output

### Symptom

Running `use "C:\Users\...\Box\...\file.dta", clear` in the Workbench produces no output at all. `sysuse auto` and `use` on files in `%TEMP%` work fine.

### Root Cause

mcp-stata v3.3+ added a path security check. Any quoted path in a `use` (or `do`) command is validated against an allowlist: the workspace CWD, system temp, and `MCP_STATA_ALLOWED_ROOTS`. Paths under Box Drive, OneDrive, or other user directories outside the workspace are blocked by default. When blocked, the command is rejected silently — the Workbench shows no output and no error.

### Fix

Add `MCP_STATA_ALLOWED_ROOTS` to the `env` block in `%APPDATA%\Code\User\mcp.json` (see config above). Setting it to `C:\Users\<username>` covers Box, OneDrive, Documents, and everything else under the user profile. Clear the discovery cache and restart VS Code.
