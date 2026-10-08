# chronos-mcp

A tiny [Model Context Protocol](https://modelcontextprotocol.io) server that gives LLMs a reliable clock: the current date and time in any IANA timezone, plus timezone conversion.

Language models have no clock. Without a tool they guess the date from their training data or the system prompt. A tool call returns the real time at the moment of the request, even in long sessions.

- Three read-only tools, no side effects
- No external APIs, no API keys, no registration
- Streamable HTTP (default) or stdio
- Hardened container: non-root, read-only filesystem, no capabilities, ~90 MB image

## Tools

| Tool | Parameters | Returns |
| --- | --- | --- |
| `get_current_time` | `timezone` (optional; string or list of up to 10 zones) | Per zone: ISO 8601 timestamp, date, time, weekday, UTC offset, abbreviation (e.g. CEST), DST flag, ISO week, Unix time |
| `convert_time` | `time` (`HH:MM` or ISO datetime), `source_timezone`, `target_timezones` (list) | The time in each target zone, offset difference in hours (`hours_vs_source`) and day change (`day_change`) |
| `list_timezones` | `filter` (optional substring, e.g. `Europe` or `Tokyo`) | Matching IANA names, at most 50 |

Example response of `get_current_time` for `Europe/Berlin`:

```json
{
  "timezone": "Europe/Berlin",
  "iso": "2026-10-08T14:32:05+02:00",
  "date": "2026-10-08",
  "time": "14:32:05",
  "weekday": "Thursday",
  "utc_offset": "+02:00",
  "abbreviation": "CEST",
  "is_dst": true,
  "iso_week": 41,
  "unix": 1791462725
}
```

Behaviour:

- The current time is read once in UTC and converted per zone, so all zones in one response describe the exact same instant.
- Unknown zones return an error with up to 5 close matches (`Europe/Berln` → `Europe/Berlin`), so the model can correct itself.
- Common short forms (`CET`, `MEZ`, `GMT`, `Berlin`, `NYC`, `Tokyo`, …) are mapped to IANA names.
- At most 10 zones per call and 50 results from `list_timezones`.

## Quick start

```bash
git clone https://github.com/aks-jp/chronos-mcp.git
cd chronos-mcp
cp .env.example .env        # optional, adjust defaults
docker compose up -d --build
docker compose ps           # wait for "healthy"
curl -s http://127.0.0.1:8765/health
```

Call a tool directly:

```bash
curl -s http://127.0.0.1:8765/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_current_time","arguments":{"timezone":["Europe/Berlin","Asia/Tokyo"]}}}'
```

Or inspect it interactively with the [MCP Inspector](https://github.com/modelcontextprotocol/inspector):

```bash
npx @modelcontextprotocol/inspector   # connect to http://127.0.0.1:8765/mcp (Streamable HTTP)
```

## Configuration

All configuration is done via environment variables (see `.env.example`).

| Variable | Default | Description |
| --- | --- | --- |
| `DEFAULT_TIMEZONE` | `UTC` | Zone used when `get_current_time` is called without arguments |
| `WEEKDAY_LANG` | `en` | Language of the `weekday` field: `en` or `de` |
| `MCP_TRANSPORT` | `streamable-http` | `streamable-http` or `stdio` |
| `MCP_HOST` | `0.0.0.0` | Bind address inside the container |
| `MCP_PORT` | `8765` | Port inside the container |

## Connecting an MCP client

The compose file publishes the server on `127.0.0.1:8765` only. It is meant to be used by an MCP client or AI gateway running on the same host and is not reachable from outside. There is no authentication between client and server; keep it bound to localhost and let the client handle user authentication.

**Streamable HTTP** – register an MCP server with the URL:

```
http://127.0.0.1:8765/mcp
```

**stdio** – for clients that spawn MCP servers as subprocesses:

```json
{
  "mcpServers": {
    "time": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "-e", "MCP_TRANSPORT=stdio", "chronos-mcp:1.0.0"]
    }
  }
}
```

Tip: add a sentence to your system prompt such as *"For the current date or time, always call `get_current_time` instead of guessing."*

## Updating

```bash
git pull && docker compose up -d --build
```

### Timezone data

Timezone rules change from time to time (DST abolished, new offsets). The server uses the pinned [`tzdata`](https://pypi.org/project/tzdata/) package only; the container sets `PYTHONTZPATH=""` so the OS zone files are ignored. To pick up new rules, bump `tzdata` in `requirements.txt`, run the tests and rebuild. Doing this at least twice a year is a good habit.

## Clock source

Containers share the host kernel clock. Make sure the host is synchronised via NTP (`timedatectl status` → `System clock synchronized: yes`). The host timezone does not matter, since all calculations start from UTC.

## Security

- Port bound to `127.0.0.1` only
- Runs as non-root UID 10001 with a read-only root filesystem
- All Linux capabilities dropped, `no-new-privileges`
- Limited to 128 MB RAM and 0.5 CPU
- Log rotation 3 × 10 MB; tool calls carry no personal data

## Development

Requires Python 3.12.

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

Tests pin the clock via `server._now()` and cover DST transitions, half- and quarter-hour offsets, the date line, aliases and typo suggestions.

## License

[MIT](LICENSE)
