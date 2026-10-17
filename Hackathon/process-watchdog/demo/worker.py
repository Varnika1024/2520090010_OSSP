#!/usr/bin/env python3
"""Sample long-running worker used for the demo. Prints a heartbeat every second."""
import argparse
import os
import time

ap = argparse.ArgumentParser()
ap.add_argument("--name", default="worker")
ap.add_argument("--crash-after", type=float, help="exit with code 1 after this many seconds")
args = ap.parse_args()

start = time.time()
while True:
    print(f"[{args.name}] pid={os.getpid()} alive for {time.time() - start:.0f}s", flush=True)
    if args.crash_after is not None and time.time() - start >= args.crash_after:
        raise SystemExit(1)
    time.sleep(1)
