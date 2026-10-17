"""Automated tests. Run from the repo root:  python3 -m unittest discover -v"""
import logging
import os
import signal
import subprocess
import sys
import time
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import ConfigError, TargetSpec, parse_config, parse_target  # noqa: E402
from restarter import RestartPolicy  # noqa: E402
from watchdog import Watchdog  # noqa: E402

PY = sys.executable
SLEEPER = [PY, "-c", "import time; time.sleep(120)"]
log = logging.getLogger("watchdog-test")
log.addHandler(logging.NullHandler())


def make_wd(*specs):
    from config import Config
    cfg = Config(interval_sec=0.1, log_file=None, targets=list(specs))
    return Watchdog(cfg, log)


def spec(name="t", cmd=SLEEPER, **kw):
    kw.setdefault("backoff_base_sec", 0)
    kw.setdefault("cwd", ".")
    return TargetSpec(name=name, cmd=cmd, **kw)


def run_until(wd, cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        wd.tick()
        if cond():
            return True
        time.sleep(0.05)
    return False


class WatchdogCase(unittest.TestCase):
    def tearDown(self):
        wd = getattr(self, "wd", None)
        if wd:
            wd.cfg.stop_children_on_exit = True
            wd.shutdown()


class TestRestart(WatchdogCase):
    def _kill_and_expect_restart(self, sig):
        self.wd = make_wd(spec())
        self.wd.start_all()
        t = self.wd.targets["t"]
        old = t.proc.pid
        os.kill(old, sig)
        self.assertTrue(run_until(self.wd, lambda: t.proc.pid != old and t.proc.is_alive()))
        self.assertEqual(t.proc.launch_count, 2)

    def test_restart_after_sigkill(self):
        self._kill_and_expect_restart(signal.SIGKILL)

    def test_restart_after_sigterm(self):
        self._kill_and_expect_restart(signal.SIGTERM)

    def test_restart_after_self_exit(self):
        self.wd = make_wd(spec(cmd=[PY, "-c", "import time; time.sleep(0.3); raise SystemExit(1)"]))
        self.wd.start_all()
        t = self.wd.targets["t"]
        self.assertTrue(run_until(self.wd, lambda: t.proc.launch_count >= 2))

    def test_multiple_targets_restart_independently(self):
        self.wd = make_wd(spec("a"), spec("b"))
        self.wd.start_all()
        a, b = self.wd.targets["a"], self.wd.targets["b"]
        old = (a.proc.pid, b.proc.pid)
        os.kill(old[0], signal.SIGKILL)
        os.kill(old[1], signal.SIGKILL)
        self.assertTrue(run_until(self.wd, lambda: a.proc.pid != old[0] and b.proc.pid != old[1]
                                  and a.proc.is_alive() and b.proc.is_alive()))

    def test_healthy_process_is_not_restarted(self):
        self.wd = make_wd(spec())
        self.wd.start_all()
        for _ in range(10):
            self.wd.tick()
            time.sleep(0.05)
        self.assertEqual(self.wd.targets["t"].proc.launch_count, 1)

    def test_clean_exit_not_restarted_when_disabled(self):
        self.wd = make_wd(spec(cmd=[PY, "-c", "pass"], restart_on_clean_exit=False))
        self.wd.start_all()
        t = self.wd.targets["t"]
        self.assertTrue(run_until(self.wd, lambda: t.finished))
        self.assertEqual(t.proc.launch_count, 1)


class TestCrashLoop(WatchdogCase):
    def test_gives_up_after_retry_limit(self):
        self.wd = make_wd(spec(cmd=[PY, "-c", "raise SystemExit(1)"], max_retries=3))
        self.wd.start_all()
        t = self.wd.targets["t"]
        self.assertTrue(run_until(self.wd, lambda: t.policy.gave_up))
        self.assertEqual(t.proc.launch_count, 4)   # 1 initial start + 3 restarts

    def test_missing_executable_is_handled(self):
        self.wd = make_wd(spec(cmd=["/nonexistent/binary"], max_retries=2))
        self.wd.start_all()
        t = self.wd.targets["t"]
        self.assertTrue(run_until(self.wd, lambda: t.policy.gave_up))


class TestAdoption(WatchdogCase):
    def test_adopts_running_process_then_restarts_it(self):
        marker = "wd-marker-" + uuid.uuid4().hex
        external = subprocess.Popen([PY, "-c", f"import time; time.sleep(120)  # {marker}", marker])
        try:
            self.wd = make_wd(spec(match=marker, cmd=[PY, "-c", "import time; time.sleep(120)", marker]))
            self.wd.start_all()
            t = self.wd.targets["t"]
            self.assertEqual(t.proc.pid, external.pid)
            self.assertEqual(t.proc.launch_count, 0)      # adopted, not launched
            external.kill()                                # leaves a zombie until waited on
            self.assertTrue(run_until(self.wd, lambda: t.proc.launch_count == 1 and t.proc.is_alive()))
            self.assertNotEqual(t.proc.pid, external.pid)
        finally:
            external.kill()
            external.wait()


class TestPolicy(unittest.TestCase):
    def test_backoff_doubles_and_is_capped(self):
        p = RestartPolicy(spec(backoff_base_sec=1, backoff_max_sec=5, max_retries=10, window_sec=1000))
        delays = [p.on_failure(i) for i in range(5)]
        self.assertEqual(delays, [1, 2, 4, 5, 5])

    def test_backoff_resets_after_stable_uptime(self):
        p = RestartPolicy(spec(backoff_base_sec=1, max_retries=10, window_sec=1000, stable_sec=30))
        p.on_failure(0); p.on_failure(1)
        p.note_started(2)
        p.note_healthy(40)
        self.assertEqual(p.on_failure(41), 1)

    def test_old_failures_leave_the_window(self):
        p = RestartPolicy(spec(max_retries=2, window_sec=10))
        self.assertIsNotNone(p.on_failure(0))
        self.assertIsNotNone(p.on_failure(1))
        self.assertIsNotNone(p.on_failure(50))             # earlier failures expired
        self.assertFalse(p.gave_up)

    def test_gives_up_when_limit_exceeded(self):
        p = RestartPolicy(spec(max_retries=2, window_sec=10))
        p.on_failure(0); p.on_failure(1)
        self.assertIsNone(p.on_failure(2))
        self.assertTrue(p.gave_up)


class TestConfig(unittest.TestCase):
    def test_string_cmd_is_split(self):
        s = parse_target({"name": "x", "cmd": "python3 a.py --flag 1"})
        self.assertEqual(s.cmd, ["python3", "a.py", "--flag", "1"])

    def test_missing_name_rejected(self):
        with self.assertRaises(ConfigError):
            parse_target({"cmd": "sleep 1"})

    def test_missing_cmd_rejected(self):
        with self.assertRaises(ConfigError):
            parse_target({"name": "x"})

    def test_negative_retries_rejected(self):
        with self.assertRaises(ConfigError):
            parse_target({"name": "x", "cmd": "sleep 1", "max_retries": -1})

    def test_duplicate_names_rejected(self):
        p = {"name": "x", "cmd": "sleep 1"}
        with self.assertRaises(ConfigError):
            parse_config({"processes": [p, dict(p)]})

    def test_empty_process_list_rejected(self):
        with self.assertRaises(ConfigError):
            parse_config({"processes": []})


if __name__ == "__main__":
    unittest.main(verbosity=2)
