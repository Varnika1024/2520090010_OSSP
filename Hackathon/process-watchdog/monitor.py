"""Process monitoring: find, launch, inspect and stop one watched process."""
import os
import signal
import subprocess
from typing import Optional

import psutil


class ManagedProcess:
    """Wraps one watched process.

    The process is either launched by the watchdog (we hold a Popen handle and can
    read its exit status) or adopted because it was already running (we only hold
    a psutil handle).
    """

    def __init__(self, spec):
        self.spec = spec
        self.popen: Optional[subprocess.Popen] = None
        self.ps: Optional[psutil.Process] = None
        self.launch_count = 0

    # ---- discovery -------------------------------------------------------
    def adopt_existing(self):
        """Attach to an already-running process whose command line contains spec.match."""
        if not self.spec.match:
            return None
        me = os.getpid()
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                if proc.info["pid"] == me:
                    continue
                cmdline = " ".join(proc.info["cmdline"] or [])
                if self.spec.match in cmdline and proc.status() != psutil.STATUS_ZOMBIE:
                    self.ps = proc
                    self.popen = None
                    return proc.pid
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    # ---- lifecycle -------------------------------------------------------
    def launch(self):
        out = subprocess.DEVNULL
        opened = None
        if self.spec.output_file:
            os.makedirs(os.path.dirname(os.path.abspath(self.spec.output_file)), exist_ok=True)
            opened = out = open(self.spec.output_file, "ab")
        try:
            self.popen = subprocess.Popen(
                self.spec.cmd,
                cwd=self.spec.cwd,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT if out is not subprocess.DEVNULL else subprocess.DEVNULL,
                start_new_session=True,   # Ctrl-C in the terminal must not hit the children directly
            )
        finally:
            if opened:
                opened.close()
        self.ps = None
        self.launch_count += 1
        return self.popen.pid

    @property
    def pid(self):
        if self.popen is not None:
            return self.popen.pid
        return self.ps.pid if self.ps else None

    def is_alive(self):
        if self.popen is not None:
            return self.popen.poll() is None
        if self.ps is None:
            return False
        try:
            return self.ps.is_running() and self.ps.status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False

    def exit_reason(self):
        """Human-readable reason for the termination, plus the exit code if known."""
        if self.popen is not None:
            rc = self.popen.poll()
            if rc is None:
                return "still running", None
            if rc < 0:
                try:
                    return f"killed by signal {signal.Signals(-rc).name}", rc
                except ValueError:
                    return f"killed by signal {-rc}", rc
            return f"exited with code {rc}", rc
        return "process disappeared", None

    def stop(self, timeout=5.0):
        """Terminate a process we launched (adopted processes are left alone)."""
        if self.popen is None or self.popen.poll() is not None:
            return
        self.popen.terminate()
        try:
            self.popen.wait(timeout)
        except subprocess.TimeoutExpired:
            self.popen.kill()
            self.popen.wait()
