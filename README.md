# chronos-mcp

A tiny [Model Context Protocol](https://modelcontextprotocol.io) server that gives LLMs a reliable clock: the current date and time in any IANA timezone, timezone conversion, date arithmetic with working days, and German public holidays.

Language models have no clock. Without a tool they guess the date from their training data or the system prompt. A tool call returns the real time at the moment of the request, even in long sessions. Models are also unreliable at calendar math (month ends, leap years, working days), so the server does that too.

- Five read-only tools, no side effects (annotated with `readOnlyHint`, so clients that only allow read-only tools accept them)
- No external APIs, no API keys, no registration
- Streamable HTTP (default) or stdio
- Hardened container: non-root, read-only filesystem, no capabilities, ~90 MB image

## Tools

| Tool | Parameters | Returns |
| --- | --- | --- |
| `get_current_time` | `timezone` (optional; string or list of up to 10 zones) | Per zone: ISO 8601 timestamp, date, time, weekday, UTC offset, abbreviation (e.g. CEST), DST flag, ISO week, Unix time |
| `convert_time` | `time` (`HH:MM` or ISO datetime), `source_timezone`, `target_timezones` (list) | The time in each target zone, offset difference in hours (`hours_vs_source`) and day change (`day_change`) |
| `list_timezones` | `filter` (optional substring, e.g. `Europe` or `Tokyo`) | Matching IANA names, at most 50 |
| `date_calc` | `operation` (`add`, `diff`, `info`, `workdays`, `add_workdays`), `date`, `end_date`, `days`, `weeks`, `months`, `state`, `timezone` (see below) | Calculated date or difference, with weekday |
| `holidays` | `year` (default: current year), `state` (default: `DEFAULT_STATE`), `date` (optional, checks one day), `timezone` | Statutory public holidays of a German state with date, weekday, name and `nationwide` flag, or for `date`: `is_holiday` and the name |

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

### date_calc

Dates are ISO `YYYY-MM-DD` or `today` (today in `DEFAULT_TIMEZONE`, or in `timezone` if given). Only `operation` is required; `date` defaults to `today`.

| `operation` | Uses | Result |
| --- | --- | --- |
| `add` | `date`, `months`, `weeks`, `days` (negative values subtract) | `result`, `weekday`, `month_end_clamped`. Months are added first, then weeks and days. A day past the end of the target month is clamped: 2026-01-31 + 1 month = 2026-02-28, 2024-01-31 + 1 month = 2024-02-29 |
| `diff` | `date`, `end_date` | `days`; `weeks` + `weeks_remainder_days`; calendar `months` + `months_remainder_days`. Negative if `end_date` is before `date`. Months count like `add`, so 2026-01-31 → 2026-02-28 is 1 month 0 days |
| `info` | `date`, optional `state` | `weekday`, `iso_week`, `iso_year`, `day_of_year`, `days_in_month`, `is_leap_year`, `is_workday`; with `state` also `holiday` |
| `workdays` | `date`, `end_date`, optional `state` | Working days (Mon–Fri) from `date` to `end_date`, **both inclusive** (Mon–Fri of one week = 5), `calendar_days`; with `state` also the excluded holidays |
| `add_workdays` | `date`, `days` (working days, negative goes back), optional `state` | The date `days` working days later; `date` itself is not counted (Friday + 1 = Monday). With `state` also the skipped holidays |

Without `state`, only weekends count as non-working days. With `state` (e.g. `NW`, `Bayern`), that state's public holidays are excluded as well (see `holidays`; Mariä Himmelfahrt counts for all of Bavaria). Limits: dates 0001-01-01 to 9999-12-31, holidays 1995–2100, at most 10000 days for `add_workdays`.

Examples (arguments → response, shortened):

```text
{"operation":"add","date":"2024-01-31","months":1}
→ {"date":"2024-01-31","result":"2024-02-29","weekday":"Thursday","month_end_clamped":true}

{"operation":"diff","date":"2026-10-19","end_date":"2026-12-24"}
→ {"days":66,"weeks":9,"weeks_remainder_days":3,"months":2,"months_remainder_days":5, ...}

{"operation":"info","date":"2026-11-18","state":"SN"}
→ {"weekday":"Wednesday","iso_week":47,"day_of_year":322,"state":"SN","holiday":"Buß- und Bettag","is_workday":false, ...}

{"operation":"workdays","date":"2026-12-21","end_date":"2027-01-08","state":"BY"}
→ {"workdays":12,"calendar_days":19,"holidays_excluded_count":3,
   "holidays_excluded":[{"date":"2026-12-25","weekday":"Friday","name":"1. Weihnachtstag"}, ...]}

{"operation":"add_workdays","date":"2026-04-02","days":1,"state":"NW"}
→ {"result":"2026-04-07","weekday":"Tuesday","holidays_skipped":[{"name":"Karfreitag", ...},{"name":"Ostermontag", ...}]}
```

### holidays

Statutory public holidays in Germany, computed locally (no external API): Easter by the anonymous Gregorian algorithm, the movable feasts derived from it, and the state-specific holidays according to the state holiday laws, including one-offs (Reformationstag nationwide in 2017; Berlin: 8 May 2020 and 2025, 17 June 2028). Years 1995–2100.

`state` accepts the codes `BW`, `BY`, `BE`, `BB`, `HB`, `HH`, `HE`, `MV`, `NI`, `NW`, `RP`, `SL`, `SN`, `ST`, `SH`, `TH`, the German or English names (`Bayern`, `Bavaria`, `Thüringen`, `Thueringen`), short forms such as `NRW`, `RLP`, `NDS`, and ISO codes like `DE-NW`. Unknown names return close matches.

Holiday names are always German (`Fronleichnam`, `Buß- und Bettag`): they are proper names, unambiguous and what a German calendar shows. The `weekday` field follows `WEEKDAY_LANG`.

```text
{"year":2026,"state":"Bayern"}
→ {"year":2026,"state":"BY","state_name":"Bayern","count":13,"holidays":[
     {"date":"2026-01-01","weekday":"Thursday","name":"Neujahr","nationwide":true},
     {"date":"2026-01-06","weekday":"Tuesday","name":"Heilige Drei Könige","nationwide":false},
     ...
     {"date":"2026-08-15","weekday":"Saturday","name":"Mariä Himmelfahrt","nationwide":false,
      "note":"Only in municipalities with a predominantly Catholic population (about 1,700 of 2,056); counted as a holiday here"},
     ...],
   "notes":["Augsburger Hohes Friedensfest (8 August) is a holiday only in the city of Augsburg; not included"]}

{"date":"2026-11-18","state":"SN"}
→ {"date":"2026-11-18","weekday":"Wednesday","state":"SN","state_name":"Sachsen","is_holiday":true,"holiday":"Buß- und Bettag"}
```

Not included: holidays that apply only in some municipalities (Fronleichnam in parts of Saxony and Thuringia, the Augsburg peace festival); the response says so in `notes`. Ostersonntag and Pfingstsonntag are listed for Brandenburg only, where the law names them. Holiday laws change rarely, but they do: new holidays need a code change.

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
| `DEFAULT_STATE` | `NW` | German state used by `holidays` when called without `state` (code or name, e.g. `BY`, `Bayern`). `date_calc` excludes holidays only if `state` is passed explicitly |
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
      "args": ["run", "-i", "--rm", "-e", "MCP_TRANSPORT=stdio", "chronos-mcp:1.1.0"]
    }
  }
}
```

Tip: add a sentence to your system prompt such as *"For the current date or time, always call `get_current_time` instead of guessing. Use `date_calc` for date arithmetic and `holidays` for public holidays."*

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

Tests pin the clock via `server._now()` and cover DST transitions, half- and quarter-hour offsets, the date line, aliases and typo suggestions, date math edge cases (leap years, month ends, negative values, working days with holidays) and the holidays of all states across several years.

## License

[MIT](LICENSE)
