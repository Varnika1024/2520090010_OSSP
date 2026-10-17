# Project Report: Linux Process Watchdog and Auto-Restart System

**Hackathon:** 17.10.2026  **Team:** [Team Name]  **Members:** [Member 1], [Member 2], [Member 3], [Member 4]

## 1. Abstract

Long-running programs crash: segmentation faults, unhandled exceptions, out-of-memory kills, or an
accidental `kill`. When nobody notices, the service stays down. This project implements a watchdog for
Linux that continuously monitors a configured set of processes and restarts any that terminate
unexpectedly. It uses exponential backoff and a retry limit so that a permanently broken program does
not cause an endless restart storm, and it records every event in a log. The system is written in
Python 3 using `subprocess` and `psutil`, is driven by a JSON file, and is covered by 19 automated tests.

## 2. Problem statement

> Develop a system that continuously monitors selected processes and automatically restarts them when
> they terminate unexpectedly.

## 3. Objectives

1. Monitor a user-defined list of processes continuously.
2. Detect unexpected termination within one polling interval.
3. Restart processes automatically with a safe restart policy.
4. Log every event so failures can be audited.
5. Do all of this without root and without affecting any other process.

## 4. System design

See [ARCHITECTURE.md](ARCHITECTURE.md) for the diagram and design decisions. In short, a main loop calls
`tick()` every `interval_sec`. For each target, the monitor checks liveness; on failure the restart
policy decides between "restart after N seconds" and "give up"; the launcher starts a new process and
the logger records what happened.

## 5. Implementation

| Component | What it does |
|---|---|
| Launch | `subprocess.Popen` with the configured command, working directory and optional output file |
| Adopt | `psutil.process_iter` finds a running process whose command line contains `match` |
| Detect | `Popen.poll()` for launched processes, `psutil` status (including zombie) for adopted ones |
| Classify | Exit code, or the signal name when killed by a signal |
| Policy | Sliding failure window, delay = min(base x 2^n, max), reset after `stable_sec` of uptime |
| Shutdown | `SIGINT` / `SIGTERM` stop the loop and terminate launched children (`SIGTERM`, then `SIGKILL` after 5 s) |

Technologies: Linux, Python 3, `psutil`, `subprocess`, `unittest`, systemd, Git/GitHub.

## 6. Testing and validation

Run with `python3 -m unittest discover -v` (19 tests, all passing at the time of writing, about 1.4 s).

| Scenario | Method | Result |
|---|---|---|
| Hard crash | `os.kill(pid, SIGKILL)` | Detected, restarted with a new PID |
| Graceful stop | `os.kill(pid, SIGTERM)` | Detected, restarted |
| Self-exit | Child exits with code 1 | Restarted |
| Multiple targets | Two targets killed at once | Both restarted independently |
| Healthy process | Left alone for 10 cycles | Launched exactly once |
| Clean exit disabled | `restart_on_clean_exit=false`, exit code 0 | Not restarted |
| Crash loop | Child fails at launch, `max_retries=3` | 1 start + 3 restarts, then gives up |
| Missing executable | `cmd` points to a non-existent binary | Error logged, retried, then gives up (no crash) |
| Adoption and zombie | Externally started process killed but not reaped | Detected as dead, relaunched |
| Backoff | Policy unit tests | Delays 1, 2, 4, 5, 5 with cap 5; reset after stable uptime; old failures leave the window |
| Config validation | Invalid configs | Missing name or cmd, negative retries, duplicates and empty lists are rejected |

### End-to-end run

The real CLI was run with `config.json` and `config.crashloop.json` (full log in
[sample_run.log](sample_run.log)):

- `worker-a` was killed with `SIGKILL`; the watchdog logged `killed by signal SIGKILL`, waited the
  1 s backoff and started a new process. Measured time from `kill -9` to a running replacement:
  **1.12 s** (poll interval 1 s, base backoff 1 s).
- `worker-b`, which exits with code 1 on its own after 15 s, was restarted automatically.
- On `SIGTERM` the watchdog stopped both children, logged `watchdog stopped` and exited with code 0.
  No worker processes were left behind.
- The crash-loop program with `max_retries=4` was restarted after delays of 1, 2, 4 and 8 s. The fifth
  failure inside the 60 s window produced an `ERROR ... giving up` entry and the watchdog exited with code 1.

## 7. Results and impact

- A killed or crashed process is back within about one polling interval plus the backoff delay (both configurable).
- No manual action is needed to recover; every event is logged with time, reason and new PID.
- Crash loops are contained instead of consuming CPU forever.
- The same approach applies to workers, bots, daemons and long-running jobs on any Linux machine.

## 8. Responsible implementation

Only processes named in the configuration are started, adopted or restarted. The watchdog runs as an
unprivileged user and was tested on dummy programs (`demo/`) in a controlled environment. The retry limit
prevents runaway behaviour that could disturb other users or system processes.

## 9. Limitations and future work

Limitations: polling-based detection, liveness only (no health check), restarted processes lose in-memory
state, adopted processes are not stopped on exit, Linux only.

Future work: e-mail or Slack alerts when a target gives up, HTTP and port health checks, CPU and memory
threshold restarts, a web dashboard, event-driven detection with `pidfd`/`netlink`.

## 10. Team contributions

| Member | Contribution |
|---|---|
| [Member 1] | Monitoring module (`monitor.py`) |
| [Member 2] | Restart engine and policy (`restarter.py`) |
| [Member 3] | Logging, configuration, systemd unit |
| [Member 4] | Tests, documentation, presentation |

## 11. References

- Python documentation: `subprocess`, `signal`, `unittest`
- `psutil` documentation: https://psutil.readthedocs.io
- `signal(7)` and `systemd.service(5)` manual pages
