#!/usr/bin/env python3
"""Linux Process Watchdog and Auto-Restart System.

Monitors the processes listed in a JSON config and restarts them when they
terminate unexpectedly.  Usage:  python3 watchdog.py --config config.json
"""
import argparse
import signal
import sys
import threading
import time

from config import ConfigError, load_config
from logger import setup_logger
from monitor import ManagedProcess
from restarter import RestartPolicy


class Target:
    def __init__(self, spec):
        self.spec = spec
        self.proc = ManagedProcess(spec)
        self.policy = RestartPolicy(spec)
        self.restart_at = None     # monotonic time of the scheduled restart
        self.finished = False      # exited cleanly and restart_on_clean_exit is false

    @property
    def active(self):
        return not (self.policy.gave_up or self.finished)


class Watchdog:
    def __init__(self, cfg, log, clock=time.monotonic):
        self.cfg = cfg
        self.log = log
        self.clock = clock
        self.stop_event = threading.Event()
        self.targets = {s.name: Target(s) for s in cfg.targets}

    # ---- startup / shutdown ---------------------------------------------
    def start_all(self):
        for t in self.targets.values():
            pid = t.proc.adopt_existing()
            if pid:
                self.log.info("[%s] already running, monitoring pid %s", t.spec.name, pid)
                t.policy.note_started(self.clock())
            else:
                self._launch(t, first=True)

    def shutdown(self):
        if self.cfg.stop_children_on_exit:
            for t in self.targets.values():
                if t.proc.popen is not None and t.proc.is_alive():
                    self.log.info("[%s] stopping pid %s", t.spec.name, t.proc.pid)
                    t.proc.stop()
        self.log.info("watchdog stopped")

    # ---- core logic -------------------------------------------------------
    def _launch(self, t, first=False):
        now = self.clock()
        try:
            pid = t.proc.launch()
        except OSError as exc:
            self.log.error("[%s] failed to start: %s", t.spec.name, exc)
            self._schedule(t, now)
            return False
        t.restart_at = None
        t.policy.note_started(now)
        self.log.info("[%s] %s (pid %s)", t.spec.name, "started" if first else "restarted", pid)
        return True

    def _schedule(self, t, now):
        delay = t.policy.on_failure(now)
        if delay is None:
            self.log.error("[%s] %d failures within %ss, giving up (needs manual attention)",
                           t.spec.name, len(t.policy.failures), t.spec.window_sec)
            t.restart_at = None
            return
        if delay <= 0:
            self._launch(t)
        else:
            t.restart_at = now + delay
            self.log.info("[%s] restarting in %.1fs", t.spec.name, delay)

    def tick(self):
        """One monitoring cycle over all targets."""
        for t in self.targets.values():
            if not t.active:
                continue
            now = self.clock()
            if t.restart_at is not None:                      # waiting out a backoff delay
                if now >= t.restart_at:
                    self._launch(t)
                continue
            if t.proc.is_alive():
                t.policy.note_healthy(now)
                continue
            reason, code = t.proc.exit_reason()
            self.log.warning("[%s] pid %s terminated: %s", t.spec.name, t.proc.pid, reason)
            if code == 0 and not t.spec.restart_on_clean_exit:
                self.log.info("[%s] clean exit, not restarting (restart_on_clean_exit=false)", t.spec.name)
                t.finished = True
                continue
            self._schedule(t, now)

    def run(self):
        self.log.info("watchdog started, monitoring %d process(es), interval %ss",
                      len(self.targets), self.cfg.interval_sec)
        self.start_all()
        try:
            while not self.stop_event.is_set():
                self.tick()
                if not any(t.active for t in self.targets.values()):
                    self.log.error("no active targets left, exiting")
                    return 1
                self.stop_event.wait(self.cfg.interval_sec)
        finally:
            self.shutdown()
        return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Linux Process Watchdog and Auto-Restart System")
    ap.add_argument("-c", "--config", default="config.json", help="path to the JSON config (default: config.json)")
    ap.add_argument("-i", "--interval", type=float, help="override the polling interval in seconds")
    ap.add_argument("-l", "--log-file", help="override the log file path")
    ap.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = ap.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    if args.interval:
        cfg.interval_sec = args.interval
    if args.log_file:
        cfg.log_file = args.log_file
    log = setup_logger(cfg.log_file, "DEBUG" if args.verbose else cfg.log_level)

    wd = Watchdog(cfg, log)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: wd.stop_event.set())
    return wd.run()


if __name__ == "__main__":
    sys.exit(main())
