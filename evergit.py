#!/usr/bin/env python3
# evergit.py
# A modular, single-file _skeleton_ for backing up GitHub repositories.
# MIT License - © Michael Thomason 2025

from __future__ import annotations

import argparse
import json
import logging
import random
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

# Optional YAML support: present if PyYAML is installed in the environment.
try:
	import yaml  # type: ignore
	_HAS_YAML = True
except Exception:
	yaml = None  # type: ignore
	_HAS_YAML = False


# ---------------------------
# Data classes & types
# ---------------------------
@dataclass
class Config:
	"""Configuration for evergit."""
	backup_root: Path
	repos: List[str]
	sleep_seconds: float = 2.0
	randomize_sleep: bool = True

	@classmethod
	def from_dict(cls, data: Dict) -> "Config":
		root = Path(data.get("backup_root", Path.cwd() / "evergit_backups"))
		repos = list(data.get("repos", []))
		sleep_seconds = float(data.get("sleep_seconds", 2.0))
		randomize_sleep = bool(data.get("randomize_sleep", True))
		return cls(backup_root=root, repos=repos, sleep_seconds=sleep_seconds, randomize_sleep=randomize_sleep)


# ---------------------------
# Logging setup
# ---------------------------
def setup_logging(log_file: Optional[Path] = None, level: int = logging.INFO) -> None:
	"""
	Configure logging to stdout and optionally to a file.
	"""
	log_handlers = [logging.StreamHandler(sys.stdout)]
	if log_file:
		fh = logging.FileHandler(log_file, encoding="utf-8")
		log_handlers.append(fh)

	logging.basicConfig(
		level=level,
		format="[%(asctime)s] %(levelname)-7s %(message)s",
		datefmt="%Y-%m-%d %H:%M:%S",
		handlers=log_handlers,
	)


# ---------------------------
# Config loading
# ---------------------------
def load_config(path: Optional[Path]) -> Config:
	"""
	Load configuration from JSON or YAML file.
	If `path` is None or file not found, returns a default example config.
	"""
	if path is None:
		logging.info("No config file specified; using built-in fallback configuration.")
		return default_config()

	if not path.exists():
		logging.warning("Config file %s not found; using built-in fallback configuration.", str(path))
		return default_config()

	ext = path.suffix.lower()
	try:
		text = path.read_text(encoding="utf-8")
		if ext == ".toml":
			import tomllib
			data = tomllib.loads(text)
		elif ext == ".json":
			data = json.loads(text)
			logging.info("Loaded JSON configuration from %s", str(path))
		else:
			logging.warning("Unsupported config format %s; using JSON fallback", ext)
			data = json.loads(text)
	except Exception as exc:
		logging.exception("Failed to load config: %s", exc)
		return default_config()

	try:
		return Config.from_dict(data)
	except Exception as exc:
		logging.exception("Invalid config structure: %s", exc)
		return default_config()


def default_config() -> Config:
	"""Return a safe example config (used when no config provided)."""
	example_repos = [
		"https://github.com/username/repo1.git",
		"git@github.com:username/repo2.git",
	]
	default_root = Path.home() / "evergit_backups"
	return Config(backup_root=default_root, repos=example_repos, sleep_seconds=2.0, randomize_sleep=True)


# ---------------------------
# Git helpers (non-destructive)
# ---------------------------
def run_git_command(args: List[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
	"""
	Run a git subprocess command and return CompletedProcess.
	`args` should not include the leading 'git' (we add it).
	"""
	cmd = ["git"] + args
	logging.debug("Running command: %s (cwd=%s)", " ".join(cmd), str(cwd) if cwd else None)
	try:
		result = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, check=check)
		return result
	except subprocess.CalledProcessError as e:
		# Return the CalledProcessError-like CompletedProcess for callers to inspect
		logging.debug("Git command failed: %s", e)
		return subprocess.CompletedProcess(args=cmd, returncode=e.returncode, stdout=e.stdout, stderr=e.stderr)


def is_git_repo(path: Path) -> bool:
	"""Detect whether the path contains a git repository."""
	if not path.exists():
		return False
	# A quick check for .git directory or 'git rev-parse' success
	if (path / ".git").exists():
		return True
	res = run_git_command(["rev-parse", "--is-inside-work-tree"], cwd=path, check=False)
	return res.returncode == 0


def has_uncommitted_changes(path: Path) -> bool:
	"""Return True if repository at path has uncommitted changes (staged or unstaged)."""
	res = run_git_command(["status", "--porcelain"], cwd=path, check=False)
	out = (res.stdout or "").strip()
	return bool(out)


def safe_clone(repo_url: str, dest: Path) -> bool:
	"""Clone the repo_url into dest. Returns True on success."""
	logging.info("Cloning %s -> %s", repo_url, dest)
	res = run_git_command(["clone", "--mirror", repo_url, str(dest)], cwd=None, check=False)
	if res.returncode == 0:
		logging.info("Clone succeeded: %s", repo_url)
		return True
	else:
		logging.error("Clone failed for %s: %s", repo_url, (res.stderr or res.stdout).strip())
		return False


def safe_pull(dest: Path) -> bool:
	"""
	Update an existing repository. This function is intentionally conservative:
	- It will detect uncommitted changes and skip pulling to avoid destructive actions.
	- Uses 'git fetch' (mirror clones) or 'git pull' depending on repo layout.
	"""
	if not is_git_repo(dest):
		logging.warning("Path %s is not a git repository. Skipping.", dest)
		return False

	# If it's a non-bare (working) repo, check for uncommitted changes.
	# For mirror/bare repos, there is no working tree to be dirty.
	if (dest / ".git").exists() or (dest / "HEAD").exists():
		# Running status to detect uncommitted changes (works for working trees)
		if has_uncommitted_changes(dest):
			logging.warning("%s - uncommitted changes detected; skipping to avoid destructive operations.", dest.name)
			return False

	# For safety and generality, use 'git remote update' or 'git fetch --all' on bare/mirror clones.
	# Try 'git remote update' first:
	res = run_git_command(["remote", "update"], cwd=dest, check=False)
	if res.returncode == 0:
		logging.info("%s - remote update completed.", dest.name)
		return True

	# Fallback to fetch
	res = run_git_command(["fetch", "--all"], cwd=dest, check=False)
	if res.returncode == 0:
		logging.info("%s - fetch completed.", dest.name)
		return True

	# As last fallback, attempt 'git pull' (non-destructive if no changes)
	res = run_git_command(["pull"], cwd=dest, check=False)
	if res.returncode == 0:
		logging.info("%s - pull completed.", dest.name)
		return True

	logging.error("%s - update failed. See previous output.", dest.name)
	return False


# ---------------------------
# Core backup logic
# ---------------------------
def process_repo(repo_url: str, backup_root: Path, cfg: Config) -> None:
	"""
	Process a single repository: clone if missing, otherwise safely update.
	"""
	stem = repo_name_from_url(repo_url)
	dest = backup_root / stem

	logging.info("Processing repo: %s", stem)

	if not dest.exists():
		# Ensure parent dirs exist
		try:
			dest.parent.mkdir(parents=True, exist_ok=True)
		except Exception:
			logging.exception("Failed to create parent directory for %s", str(dest))
			return

		# Clone. Use mirror clones to keep full refs and reduce working tree interference.
		success = safe_clone(repo_url, dest)
		if not success:
			logging.error("Failed to clone %s; skipping further processing.", repo_url)
			return
	else:
		# Repository exists: perform a safe update
		if not is_git_repo(dest):
			logging.warning("%s exists but is not a git repository. Skipping.", dest)
			return

		# Check for uncommitted changes and update if clean
		if has_uncommitted_changes(dest):
			logging.warning("%s - uncommitted changes detected; skipping update to avoid data loss.", dest)
			return

		success = safe_pull(dest)
		if not success:
			logging.error("Failed to update %s", str(dest))
			return

	# Sleep between operations
	_sleep(cfg)


def repo_name_from_url(url: str) -> str:
	"""
	Compute a directory-safe name for the repository based on the URL.
	For example:
	- https://github.com/user/repo.git -> user_repo.git or user_repo
	- git@github.com:user/repo.git -> user_repo.git or user_repo
	"""
	# Very small sanitization; keep '.git' suffix to avoid collisions if desired.
	name = url.rstrip("/").split("/")[-1]
	owner = url.rstrip("/").split("/")[-2] if "/" in url else ""
	if owner:
		combined = f"{owner}__{name}"
	else:
		combined = name
	# Replace characters that might be problematic in filenames
	return combined.replace(":", "__").replace("@", "__").replace(" ", "_")


def _sleep(cfg: Config) -> None:
	"""Sleep for the configured time; optionally randomize slightly."""
	secs = cfg.sleep_seconds
	if cfg.randomize_sleep:
		# +/- 50% jitter
		jitter = secs * 0.5
		secs = max(0.0, random.uniform(secs - jitter, secs + jitter))
	logging.debug("Sleeping for %.2f seconds", secs)
	time.sleep(secs)


# ---------------------------
# CLI / main
# ---------------------------
def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="evergit - safe GitHub repository backup tool")
	parser.add_argument("--config", "-c", type=Path, default=None, help="Path to config file (JSON or YAML)")
	parser.add_argument("--log-file", type=Path, default=None, help="Optional path to write log output")
	parser.add_argument("--sleep", type=float, default=None, help="Override sleep seconds between repos")
	parser.add_argument("--non-random-sleep", action="store_true", help="Disable randomization of sleep interval")
	parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
	return parser.parse_args(list(argv) if argv else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
	"""Main entry point for evergit."""
	args = parse_args(argv)

	log_level = logging.DEBUG if args.verbose else logging.INFO
	setup_logging(log_file=args.log_file, level=log_level)
	logging.info("Starting evergit backup run")

	cfg = load_config(args.config)

	# Override settings from CLI if provided
	if args.sleep is not None:
		cfg.sleep_seconds = float(args.sleep)
	if args.non_random_sleep:
		cfg.randomize_sleep = False

	# Ensure backup root exists
	try:
		cfg.backup_root.mkdir(parents=True, exist_ok=True)
		logging.info("Backup root: %s", str(cfg.backup_root))
	except Exception:
		logging.exception("Could not create backup root directory: %s", str(cfg.backup_root))
		return 2

	# Iterate repositories and process each
	for repo in cfg.repos:
		try:
			process_repo(repo, cfg.backup_root, cfg)
		except Exception:
			logging.exception("Unexpected error while processing repo: %s", repo)
			# continue with remaining repos

	logging.info("Backup run complete")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
