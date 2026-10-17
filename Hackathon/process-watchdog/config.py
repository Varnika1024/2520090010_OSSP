"""Configuration loading and validation."""
import json
import os
import shlex
from dataclasses import dataclass, field
from typing import List, Optional


class ConfigError(ValueError):
    """Raised when the configuration file is invalid."""


@dataclass
class TargetSpec:
    name: str
    cmd: List[str]
    match: Optional[str] = None          # substring of a command line to adopt an already-running process
    cwd: Optional[str] = None
    output_file: Optional[str] = None    # where the child's stdout/stderr go (default: discarded)
    max_retries: int = 5                 # restarts allowed inside window_sec
    window_sec: float = 60
    backoff_base_sec: float = 1
    backoff_max_sec: float = 30
    stable_sec: float = 30               # uptime after which the backoff counter resets
    restart_on_clean_exit: bool = True   # restart even if the process exited with code 0


@dataclass
class Config:
    interval_sec: float = 2
    log_file: Optional[str] = "logs/watchdog.log"
    log_level: str = "INFO"
    stop_children_on_exit: bool = True
    targets: List[TargetSpec] = field(default_factory=list)


def _num(value, key, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
        raise ConfigError(f"'{key}' must be a number >= {minimum}, got {value!r}")
    return value


def parse_target(raw, base_dir="."):
    if not isinstance(raw, dict):
        raise ConfigError("each entry in 'processes' must be an object")
    name = raw.get("name")
    if not name or not isinstance(name, str):
        raise ConfigError("every process needs a non-empty string 'name'")
    cmd = raw.get("cmd")
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    if not cmd or not isinstance(cmd, list) or not all(isinstance(c, str) for c in cmd):
        raise ConfigError(f"process '{name}': 'cmd' must be a command string or a list of strings")

    spec = TargetSpec(name=name, cmd=cmd)
    spec.match = raw.get("match")
    cwd = raw.get("cwd") or base_dir
    spec.cwd = cwd if os.path.isabs(cwd) else os.path.normpath(os.path.join(base_dir, cwd))
    spec.output_file = raw.get("output_file")
    spec.max_retries = int(_num(raw.get("max_retries", spec.max_retries), "max_retries", 0))
    spec.window_sec = _num(raw.get("window_sec", spec.window_sec), "window_sec", 0.001)
    spec.backoff_base_sec = _num(raw.get("backoff_base_sec", spec.backoff_base_sec), "backoff_base_sec", 0)
    spec.backoff_max_sec = _num(raw.get("backoff_max_sec", spec.backoff_max_sec), "backoff_max_sec", 0)
    spec.stable_sec = _num(raw.get("stable_sec", spec.stable_sec), "stable_sec", 0)
    spec.restart_on_clean_exit = bool(raw.get("restart_on_clean_exit", True))
    return spec


def parse_config(data, base_dir="."):
    if not isinstance(data, dict):
        raise ConfigError("top level of the config must be an object")
    cfg = Config()
    cfg.interval_sec = _num(data.get("interval_sec", cfg.interval_sec), "interval_sec", 0.05)
    cfg.log_file = data.get("log_file", cfg.log_file)
    if cfg.log_file and not os.path.isabs(cfg.log_file):
        cfg.log_file = os.path.join(base_dir, cfg.log_file)
    cfg.log_level = data.get("log_level", cfg.log_level)
    cfg.stop_children_on_exit = bool(data.get("stop_children_on_exit", True))

    procs = data.get("processes")
    if not isinstance(procs, list) or not procs:
        raise ConfigError("'processes' must be a non-empty list")
    cfg.targets = [parse_target(p, base_dir) for p in procs]
    names = [t.name for t in cfg.targets]
    if len(set(names)) != len(names):
        raise ConfigError("process names must be unique")
    return cfg


def load_config(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}")
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config file is not valid JSON: {exc}")
    return parse_config(data, os.path.dirname(os.path.abspath(path)))
