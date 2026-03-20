![Image](../images/title.png)
<div align="center">

<!-- # Grok Search MCP -->

English | [简体中文](../README.md)

**Grok-with-Tavily MCP, providing enhanced web access for Claude Code**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) [![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/) [![FastMCP](https://img.shields.io/badge/FastMCP-2.0.0+-green.svg)](https://github.com/jlowin/fastmcp)

</div>

---

## 1. Overview

Grok Search MCP is an MCP server built on [FastMCP](https://github.com/jlowin/fastmcp), featuring a **dual-engine architecture**: **Grok** handles AI-driven intelligent search, while **Tavily** handles high-fidelity web content extraction and site mapping. Together they provide complete real-time web access for LLM clients such as Claude Code and Cherry Studio.

```
Claude --MCP--> Grok Search Server
                  ├─ web_search  ---> Grok API (AI Search)
                  ├─ web_fetch   ---> Tavily Extract (Content Extraction)
                  └─ web_map     ---> Tavily Map (Site Mapping)
```

### Features

- **Dual Engine**: Grok search + Tavily extraction/mapping, complementary collaboration
- **Dual API mode**: supports both OpenAI-compatible Chat Completions and xAI's official Responses API (`/v1/responses`), switchable via `GROK_API_MODE`
- **Automatic time injection** (detects time-related queries, injects local time context)
- One-click disable Claude Code's built-in WebSearch/WebFetch, force routing to this tool
- Smart retry (Retry-After header parsing + exponential backoff)
- Parent process monitoring (auto-detects parent process exit on Windows, prevents zombie processes)

### Demo

Using `cherry studio` with this MCP configured, here's how `claude-opus-4.6` leverages this project for external knowledge retrieval, reducing hallucination rates.

![](../images/wogrok.png)
As shown above, **for a fair experiment, we enabled Claude's built-in search tools**, yet Opus 4.6 still relied on its internal knowledge without consulting FastAPI's official documentation for the latest examples.

![](../images/wgrok.png)
As shown above, with `grok-search MCP` enabled under the same experimental conditions, Opus 4.6 proactively made multiple search calls to **retrieve official documentation, producing more reliable answers.**


## 2. Installation

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended Python package manager)
- Claude Code

<details>
<summary><b>Install uv</b></summary>

```bash
# Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

> Windows users are **strongly recommended** to run this project in WSL.

</details>

### One-Click Install

If you have previously installed this project, remove the old MCP first:
```
claude mcp remove grok-search
```

Replace the environment variables in the following command with your own values. The Grok endpoint must be OpenAI-compatible; Tavily is optional — `web_fetch` and `web_map` will be unavailable without it.

#### GuDa Users (Recommended)

GuDa users only need to set `GUDA_API_KEY` to access all services — API URLs are automatically derived:

```bash
claude mcp add-json grok-search --scope user '{
  "type": "stdio",
  "command": "uvx",
  "args": [
    "--from",
    "git+https://github.com/zc-libre/grok-search",
    "grok-search"
  ],
  "env": {
    "GUDA_API_KEY": "your-guda-api-key"
  }
}'
```

#### Custom Configuration

To use your own API endpoints, configure each service separately:

```bash
claude mcp add-json grok-search --scope user '{
  "type": "stdio",
  "command": "uvx",
  "args": [
    "--from",
    "git+https://github.com/zc-libre/grok-search",
    "grok-search"
  ],
  "env": {
    "GROK_API_URL": "https://your-api-endpoint.com/v1",
    "GROK_API_KEY": "your-grok-api-key",
    "TAVILY_API_KEY": "tvly-your-tavily-key",
    "TAVILY_API_URL": "https://api.tavily.com"
  }
}'
```

<details>
<summary><b>Using xAI Responses API + Multi-Agent Model</b></summary>

Set `GROK_API_MODE=responses` to enable xAI's official Responses endpoint, compatible with `grok-4.20-multi-agent` models:

```bash
claude mcp add-json grok-search --scope user '{
  "type": "stdio",
  "command": "uvx",
  "args": [
    "--from",
    "git+https://github.com/zc-libre/grok-search",
    "grok-search"
  ],
  "env": {
    "GROK_API_URL": "https://api.x.ai/v1",
    "GROK_API_KEY": "your-xai-api-key",
    "GROK_API_MODE": "responses",
    "GROK_MODEL": "grok-4.20-multi-agent-beta-0309",
    "GROK_REASONING_EFFORT": "high",
    "TAVILY_API_KEY": "tvly-your-tavily-key"
  }
}'
```

> **Note**: `grok-4.20-multi-agent` models **only work with the Responses API**. Using Chat Completions mode will return HTTP 400.

</details>

You can also configure additional environment variables in the `env` field:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GUDA_API_KEY` | No | - | GuDa API key (auto-derives all service URLs and keys when set) |
| `GUDA_BASE_URL` | No | `https://code.guda.studio` | GuDa service base URL |
| `GROK_API_URL` | No | `{GUDA_BASE_URL}/grok/v1` | Grok API endpoint (OpenAI-compatible), overrides GuDa-derived value |
| `GROK_API_KEY` | No | `{GUDA_API_KEY}` | Grok API key, overrides GuDa-derived value |
| `GROK_MODEL` | No | `grok-4.20-beta` | Default model (takes precedence over `~/.config/grok-search/config.json` when set) |
| `GROK_API_MODE` | No | `chat` | API mode: `chat` (Chat Completions) or `responses` (Responses API) |
| `GROK_REASONING_EFFORT` | No | - | Reasoning effort (Responses mode only): `low`/`medium` (4 agents), `high`/`xhigh` (16 agents) |
| `TAVILY_API_KEY` | No | `{GUDA_API_KEY}` | Tavily API key (for web_fetch / web_map) |
| `TAVILY_API_URL` | No | `{GUDA_BASE_URL}/tavily` | Tavily API endpoint |
| `TAVILY_ENABLED` | No | `true` | Enable Tavily |
| `FIRECRAWL_API_KEY` | No | `{GUDA_API_KEY}` | Firecrawl API key (fallback when Tavily fails) |
| `FIRECRAWL_API_URL` | No | `{GUDA_BASE_URL}/firecrawl` | Firecrawl API endpoint |
| `GROK_DEBUG` | No | `false` | Debug mode |
| `GROK_LOG_LEVEL` | No | `INFO` | Log level |
| `GROK_LOG_DIR` | No | `logs` | Log directory |
| `GROK_RETRY_MAX_ATTEMPTS` | No | `3` | Max retry attempts |
| `GROK_RETRY_MULTIPLIER` | No | `1` | Retry backoff multiplier |
| `GROK_RETRY_MAX_WAIT` | No | `10` | Max retry wait in seconds |

> **Note**: When `GUDA_API_KEY` is set, all `GROK_API_URL`/`GROK_API_KEY`/`TAVILY_*`/`FIRECRAWL_*` variables become optional as they are auto-derived from `GUDA_BASE_URL`. Explicitly set variables take higher priority.


### Verify Installation

```bash
claude mcp list
```

After confirming a successful connection, we **highly recommend** typing the following in a Claude conversation:
```
Call grok-search toggle_builtin_tools to disable Claude Code's built-in WebSearch and WebFetch tools
```
This will automatically modify the **project-level** `.claude/settings.json` `permissions.deny`, disabling Claude Code's built-in WebSearch and WebFetch, forcing Claude Code to use this project for searches!

### Other LLM Client Configuration

In addition to Claude Code, this project supports all MCP-compatible LLM clients. Below are configuration examples for popular clients.

<details>
<summary><b>Cursor</b></summary>

Create `.cursor/mcp.json` in your project root (project-level) or `~/.cursor/mcp.json` (global):

```json
{
  "mcpServers": {
    "grok-search": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/zc-libre/grok-search",
        "grok-search"
      ],
      "env": {
        "GROK_API_URL": "https://your-api-endpoint.com/v1",
        "GROK_API_KEY": "your-grok-api-key",
        "TAVILY_API_KEY": "tvly-your-tavily-key"
      }
    }
  }
}
```
</details>

<details>
<summary><b>Windsurf</b></summary>

Edit `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "grok-search": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/zc-libre/grok-search",
        "grok-search"
      ],
      "env": {
        "GROK_API_URL": "https://your-api-endpoint.com/v1",
        "GROK_API_KEY": "your-grok-api-key",
        "TAVILY_API_KEY": "tvly-your-tavily-key"
      }
    }
  }
}
```
</details>

<details>
<summary><b>Cline (VS Code Extension)</b></summary>

Open Cline Settings → MCP Servers → Add configuration:

```json
{
  "mcpServers": {
    "grok-search": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/zc-libre/grok-search",
        "grok-search"
      ],
      "env": {
        "GROK_API_URL": "https://your-api-endpoint.com/v1",
        "GROK_API_KEY": "your-grok-api-key",
        "TAVILY_API_KEY": "tvly-your-tavily-key"
      }
    }
  }
}
```
</details>

<details>
<summary><b>VS Code Copilot (GitHub Copilot Chat)</b></summary>

Create `.vscode/mcp.json` in your project root:

```json
{
  "servers": {
    "grok-search": {
      "type": "stdio",
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/zc-libre/grok-search",
        "grok-search"
      ],
      "env": {
        "GROK_API_URL": "https://your-api-endpoint.com/v1",
        "GROK_API_KEY": "your-grok-api-key",
        "TAVILY_API_KEY": "tvly-your-tavily-key"
      }
    }
  }
}
```
</details>

<details>
<summary><b>OpenAI Codex CLI</b></summary>

#### One-Click Command

```bash
codex mcp add grok-search \
  --env GROK_API_URL=https://your-api-endpoint.com/v1 \
  --env GROK_API_KEY=your-grok-api-key \
  --env TAVILY_API_KEY=tvly-your-tavily-key \
  -- uvx --from git+https://github.com/zc-libre/grok-search grok-search
```

#### Manual Configuration

You can also edit `~/.codex/config.toml` (global) or `.codex/config.toml` in your project:

```toml
[mcp_servers.grok-search]
command = "uvx"
args = ["--from", "git+https://github.com/zc-libre/grok-search", "grok-search"]

[mcp_servers.grok-search.env]
GROK_API_URL = "https://your-api-endpoint.com/v1"
GROK_API_KEY = "your-grok-api-key"
TAVILY_API_KEY = "tvly-your-tavily-key"
```

Verify: `codex mcp list`, or type `/mcp` in the Codex TUI.
</details>

<details>
<summary><b>Cherry Studio</b></summary>

In Cherry Studio Settings → MCP Servers → Add, select `stdio` type:

- **Command**: `uvx`
- **Args**: `--from git+https://github.com/zc-libre/grok-search grok-search`
- **Environment Variables**:
  - `GROK_API_URL`: `https://your-api-endpoint.com/v1`
  - `GROK_API_KEY`: `your-grok-api-key`
  - `TAVILY_API_KEY`: `tvly-your-tavily-key`

</details>

> 💡 All clients support the full set of environment variables listed in the table above.

## 3. MCP Tools

<details>
<summary>This project provides nine MCP tools (click to expand)</summary>

### `web_search` — AI Web Search

Executes AI-driven web search via Grok API. By default it returns only Grok's answer and a `session_id` for retrieving sources later.

`web_search` does not expand sources in the response; it only returns `sources_count`. Sources are cached server-side by `session_id` and can be fetched with `get_sources`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | - | Search query |
| `platform` | string | No | `""` | Focus platform (e.g., `"Twitter"`, `"GitHub, Reddit"`) |
| `model` | string | No | `null` | Per-request Grok model ID |
| `extra_sources` | int | No | `0` | Extra sources via Tavily/Firecrawl (0 disables) |

Automatically detects time-related keywords in queries (e.g., "latest", "today", "recent"), injecting local time context to improve accuracy for time-sensitive searches.

Return value (structured dict):
- `session_id`: search session ID
- `content`: answer only (sources removed)
- `sources_count`: cached sources count

### `x_search` — X/Twitter Search (Responses API)

Search posts on X (formerly Twitter) using xAI's x_search tool. **Only available when `GROK_API_MODE=responses`.**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | - | Search query for X posts |
| `x_handles` | string | No | `""` | Comma-separated X handles to include (max 10, without @) |
| `excluded_x_handles` | string | No | `""` | Comma-separated X handles to exclude (max 10) |
| `from_date` | string | No | `""` | Start date in ISO8601 format (e.g., `2026-03-01T00:00:00Z`) |
| `to_date` | string | No | `""` | End date in ISO8601 format |
| `image_understanding` | bool | No | `false` | Analyze images in posts |
| `video_understanding` | bool | No | `false` | Analyze videos in posts |
| `model` | string | No | `null` | Per-request Grok model ID |

Return value structure is the same as `web_search`.

### `get_sources` — Retrieve Sources

Retrieves the full cached source list for a previous `web_search` or `x_search` call.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `session_id` | string | Yes | `session_id` returned by `web_search` |

Return value (structured dict):
- `session_id`
- `sources_count`
- `sources`: source list (each item includes `url`, may include `title`/`description`/`provider`)

### `web_fetch` — Web Content Extraction

Extracts complete web content via Tavily Extract API, returning Markdown format.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | Yes | Target webpage URL |

### `web_map` — Site Structure Mapping

Traverses website structure via Tavily Map API, discovering URLs and generating a site map.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | Yes | - | Starting URL |
| `instructions` | string | No | `""` | Natural language filtering instructions |
| `max_depth` | int | No | `1` | Max traversal depth (1-5) |
| `max_breadth` | int | No | `20` | Max links to follow per page (1-500) |
| `limit` | int | No | `50` | Total link processing limit (1-500) |
| `timeout` | int | No | `150` | Timeout in seconds (10-150) |

### `get_config_info` — Configuration Diagnostics

No parameters required. Displays all configuration status, tests Grok API connection, returns response time and available model list (API keys auto-masked).

### `switch_model` — Model Switching

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `model` | string | Yes | Model ID (e.g., `"grok-4-fast"`, `"grok-2-latest"`) |

Settings persist to `~/.config/grok-search/config.json` across sessions.

### `toggle_builtin_tools` — Tool Routing Control

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `action` | string | No | `"status"` | `"on"` disable built-in tools / `"off"` enable built-in tools / `"status"` check status |

Modifies project-level `.claude/settings.json` `permissions.deny` to disable Claude Code's built-in WebSearch and WebFetch.

### `search_planning` — Search Planning

A structured multi-phase planning scaffold to generate an executable search plan before running complex searches.
</details>

## 4. FAQ

<details>
<summary>
Q: Must I configure both Grok and Tavily?
</summary>
A: Set `GUDA_API_KEY` to get full Grok + Tavily + Firecrawl service. Without GuDa, Grok (`GROK_API_URL` + `GROK_API_KEY`) is required and provides the core search capability. Tavily is optional — without it, `web_fetch` and `web_map` will return configuration error messages.
</details>

<details>
<summary>
Q: What format does the Grok API URL need?
</summary>
A: An OpenAI-compatible API endpoint. By default it uses the `/chat/completions` endpoint (`GROK_API_MODE=chat`). Set `GROK_API_MODE=responses` to switch to xAI's official Responses endpoint (`/responses`), which enables server-side tools like `web_search` and `x_search`.
</details>

<details>
<summary>
Q: How to verify configuration?
</summary>
A: Say "Show grok-search configuration info" in a Claude conversation to automatically test the API connection and display results.
</details>

## License

[MIT License](LICENSE)

---

<div align="center">

**If this project helps you, please give it a Star!**

[![Star History Chart](https://api.star-history.com/svg?repos=zc-libre/grok-search&type=date&legend=top-left)](https://www.star-history.com/#zc-libre/grok-search&type=date&legend=top-left)
</div>
