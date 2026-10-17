# Linux Process Watchdog and Auto-Restart System

A lightweight watchdog that continuously monitors selected Linux processes and
automatically restarts them when they terminate unexpectedly. Written in Python 3.
Hackathon project, 17.10.2026.

**Team:** [Team Name], [Member 1], [Member 2], [Member 3], [Member 4]

## Features

- Monitors any number of processes defined in a JSON config
- Detects crashes, `kill -9` / `kill -15`, self-exits and zombie processes
- Restarts with **exponential backoff** (1 s, 2 s, 4 s, ... up to a cap)
- **Retry limit inside a time window** stops crash loops and flags them for attention
- Can **adopt** an already-running process (by command-line match) and restart it if it dies
- Timestamped, rotating log file plus console output
- Graceful shutdown on `SIGINT` / `SIGTERM`; stops the children it launched
- Runs as a normal user; touches only the processes listed in the config

## Requirements

- Linux (uses `/proc` through `psutil`)
- Python 3.8 or newer
- `psutil` (see `requirements.txt`)

## Setup

```bash
git clone https://github.com/[team]/process-watchdog.git
cd process-watchdog
python3 -m venv .venv && source .venv/bin/activate    # optional but recommended
pip install -r requirements.txt
```

**Compilation:** none needed, Python is interpreted. To check the sources for syntax errors:

```bash
python3 -m py_compile watchdog.py monitor.py restarter.py config.py logger.py
```

## Run

```bash
python3 watchdog.py --config config.json
```

Options: `-c/--config PATH`, `-i/--interval SECONDS`, `-l/--log-file PATH`, `-v/--verbose`.
Stop it with `Ctrl-C` or `kill -TERM <watchdog pid>`.

Exit codes: `0` normal shutdown, `1` every target gave up, `2` bad config.

## Demo (about 2 minutes)

Terminal 1:

```bash
python3 watchdog.py --config config.json
```

Terminal 2:

```bash
pgrep -fa "demo/worker.py"          # note the PID of worker-a
kill -9 <pid of worker-a>           # simulate a crash
pgrep -fa "demo/worker.py"          # worker-a is back with a new PID
tail -f logs/watchdog.log           # shows: terminated, restarting, restarted
```

`worker-b` is configured to crash by itself every 15 s, so you will also see
self-exit restarts without doing anything.

Crash-loop demo (backoff, then the watchdog gives up):

```bash
python3 watchdog.py --config config.crashloop.json
```

A real log of both demos is in [`docs/sample_run.log`](docs/sample_run.log).

## Configuration

```json
{
  "interval_sec": 1,
  "log_file": "logs/watchdog.log",
  "log_level": "INFO",
  "stop_children_on_exit": true,
  "processes": [
    {
      "name": "worker-a",
      "cmd": "python3 demo/worker.py --name worker-a",
      "max_retries": 5,
      "window_sec": 60,
      "backoff_base_sec": 1,
      "backoff_max_sec": 30
    }
  ]
}
```

Top level:

| Key | Default | Meaning |
|---|---|---|
| `interval_sec` | 2 | Seconds between monitoring cycles |
| `log_file` | `logs/watchdog.log` | Log path (relative paths are relative to the config file); `null` for console only |
| `log_level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `stop_children_on_exit` | `true` | Stop processes the watchdog launched when it shuts down |

Per process:

| Key | Default | Meaning |
|---|---|---|
| `name` | required | Unique label used in logs |
| `cmd` | required | Command, as a string or a list of arguments |
| `match` | none | Substring of a command line; if a matching process is already running it is adopted instead of launched |
| `cwd` | config file's folder | Working directory for the process |
| `output_file` | discarded | File that receives the process's stdout/stderr |
| `max_retries` | 5 | Restarts allowed within `window_sec`; one more failure and the watchdog gives up |
| `window_sec` | 60 | Length of the retry window |
| `backoff_base_sec` | 1 | First restart delay, doubled after each consecutive failure |
| `backoff_max_sec` | 30 | Upper bound for the delay |
| `stable_sec` | 30 | Uptime after which the backoff resets to the base delay |
| `restart_on_clean_exit` | `true` | Restart even if the process exited with code 0 |

## Tests

```bash
python3 -m unittest discover -v
```

19 tests start real processes and check that they are killed and restarted
(`SIGKILL`, `SIGTERM`, self-exit, several targets at once, adoption of an
external process, zombie handling, crash loop, missing executable) plus unit
tests for the backoff policy and config validation. Results are in
[`docs/PROJECT_REPORT.md`](docs/PROJECT_REPORT.md).

## Run at boot with systemd

Edit `deploy/process-watchdog.service` (user and paths), then:

```bash
sudo cp deploy/process-watchdog.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now process-watchdog
journalctl -u process-watchdog -f
```

systemd restarts the watchdog itself if it ever dies, so nothing is left unwatched.

## Project layout

```
watchdog.py     main loop, CLI, signal handling
monitor.py      find / launch / inspect / stop one process
restarter.py    retry limit and exponential backoff
config.py       config loading and validation
logger.py       console and rotating-file logging
config.json     demo config (two workers)
config.crashloop.json   crash-loop demo config
demo/           sample worker and crash-loop programs
tests/          automated tests
deploy/         systemd unit file
docs/           architecture notes, project report, sample log
```

## Safe use

Only processes named in the config are started, adopted or restarted. Use the
demo programs for testing; do not point the watchdog at system services you do
not own. Retry limits prevent runaway restart loops.

## Limitations

- Polling-based: a crash is noticed at the next cycle, so detection time is up to `interval_sec`
- Checks that the process is alive, not that it is healthy (no HTTP or port checks yet)
- A restarted process starts fresh; in-memory state is lost
- Adopted processes are monitored but not stopped when the watchdog exits (they were not started by it)
- Linux only
