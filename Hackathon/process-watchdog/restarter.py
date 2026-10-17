"""Restart policy: retry limit inside a time window, with exponential backoff."""
from collections import deque
from typing import Optional


class RestartPolicy:
    def __init__(self, spec):
        self.spec = spec
        self.failures = deque()      # timestamps of recent failures
        self.consecutive = 0         # consecutive failures, drives the backoff
        self.up_since = None
        self.gave_up = False

    def note_started(self, now):
        self.up_since = now

    def note_healthy(self, now):
        """Reset the backoff once the process has stayed up for stable_sec."""
        if self.up_since is not None and now - self.up_since >= self.spec.stable_sec:
            self.consecutive = 0

    def on_failure(self, now) -> Optional[float]:
        """Register a failure.

        Returns the delay (seconds) before the next restart, or None when the
        retry limit has been exceeded and the watchdog should stop trying.
        """
        self.up_since = None
        while self.failures and now - self.failures[0] > self.spec.window_sec:
            self.failures.popleft()
        self.failures.append(now)
        if len(self.failures) > self.spec.max_retries:
            self.gave_up = True
            return None
        delay = min(self.spec.backoff_base_sec * (2 ** self.consecutive), self.spec.backoff_max_sec)
        self.consecutive += 1
        return delay
