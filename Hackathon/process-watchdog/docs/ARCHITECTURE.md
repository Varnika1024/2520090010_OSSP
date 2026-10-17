# Architecture

```
 config.json --> [ Config loader ] --> Watchdog main loop
                                          |  every interval_sec
                                          v
                              [ Monitor ]  checks pid / state of each target
                                          |  dead?
                                          v
                              [ Restart policy ]  retry limit + backoff
                                  |            |
                       delay / restart       give up
                                  v            v
                           [ launch process ]  [ log ERROR ]
                                  |
                                  v
                            [ Event logger ] --> console + logs/watchdog.log
```

## Modules

| File | Responsibility |
|---|---|
| `watchdog.py` | `Watchdog` class: startup, `tick()` (one monitoring cycle), shutdown; CLI and signal handlers |
| `monitor.py` | `ManagedProcess`: launches with `subprocess.Popen`, adopts running processes via `psutil`, liveness check, exit reason (exit code or signal name), graceful stop |
| `restarter.py` | `RestartPolicy`: sliding window of failures, exponential backoff, give-up decision, backoff reset after stable uptime |
| `config.py` | Typed `TargetSpec` / `Config`, validation with clear error messages |
| `logger.py` | Console handler plus 1 MB x 3 rotating file handler |

## One monitoring cycle (`Watchdog.tick`)

For every active target:

1. If a restart is already scheduled, launch it when its delay has passed.
2. If the process is alive, let the policy reset the backoff once uptime exceeds `stable_sec`.
3. Otherwise log why it ended (`killed by signal SIGKILL`, `exited with code 1`, `process disappeared`).
4. If it exited with code 0 and `restart_on_clean_exit` is false, mark it finished.
5. Ask the policy for a delay. `None` means too many failures inside the window: log an error and stop retrying that target.
6. Delay 0 restarts immediately; otherwise the restart is scheduled.

## Design decisions

- **Polling, not event-driven.** `Popen.poll()` and `psutil` need no root and work for adopted processes. The interval is configurable (default 1 to 2 s).
- **Children start in their own session** (`start_new_session=True`), so a terminal `Ctrl-C` does not hit them directly and the watchdog controls their shutdown.
- **Zombies count as dead.** A process that exited but was not reaped is treated as terminated.
- **Backoff plus window.** Backoff protects the machine from a hot restart loop; the window limit makes the watchdog stop and ask for human attention instead of retrying forever.
- **Time is injected** (`clock` parameter), and `tick()` is a plain method, which keeps the logic testable without sleeping.
- **systemd supervises the watchdog itself**, solving "who watches the watcher".
