#!/usr/bin/env python3
# evergit.py
# Single-file for backing up GitHub repositories.
# MIT License - © Michael Thomason 2025

import argparse
import json
import logging
import os
import pathlib
import random
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, IO, List, Optional, Tuple

try:
	import fcntl
except ImportError:  # Windows
	fcntl = None  # type: ignore[assignment]

try:
	import tomllib
except ModuleNotFoundError:  # Python < 3.11
	tomllib = None  # type: ignore[assignment]

# --- Constants ---
DEFAULT_CONFIG_PATHS: List[str] = ["evergit.toml", "evergit.json"]
DEFAULT_BACKUP_ROOT: str = "~/evergit_backups"
DEFAULT_SLEEP_SECONDS: float = 3.0
DEFAULT_RANDOMIZE_SLEEP: bool = True
DEFAULT_MAX_AGE_HOURS: float = 23.0
STATE_FILENAME: str = ".evergit_last_success"
GIT_TIMEOUT_SECONDS: float = 3600.0

# --- Logging ---

def setup_logging(log_file: Optional[str] = None) -> None:
	"""Configures the logging format and destination."""
	handlers: List[logging.Handler] = [logging.StreamHandler()]
	if log_file:
		try:
			handlers.append(logging.FileHandler(log_file))
		except OSError as e:
			logging.error(f"Could not open log file {log_file}: {e}")
			sys.exit(1)

	logging.basicConfig(
		level=logging.INFO,
		format='[%(asctime)s] %(levelname)-7s %(message)s',
		datefmt='%Y-%m-%d %H:%M:%S',
		handlers=handlers
	)

# --- Command line ---

def parse_arguments() -> argparse.Namespace:
	"""Parses command-line arguments."""
	parser = argparse.ArgumentParser(description="A cross-platform, non-destructive GitHub repository backup script.")
	parser.add_argument(
		'--config',
		type=str,
		default=None,
		help=f"Path to a TOML or JSON configuration file. Defaults to searching for {', '.join(DEFAULT_CONFIG_PATHS)} next to the script and in the current directory."
	)
	parser.add_argument(
		'--log-file',
		type=str,
		default=None,
		help="Path to an optional log file."
	)
	parser.add_argument(
		'--backup-root',
		type=str,
		default=None,
		help="Override the backup root directory specified in the config file."
	)
	parser.add_argument(
		'--sleep-seconds',
		type=float,
		default=None,
		help="Override the sleep duration in seconds between repositories."
	)
	parser.add_argument(
		'--no-randomize-sleep',
		action='store_true',
		help="Disable sleep randomization."
	)
	parser.add_argument(
		'--if-due',
		action='store_true',
		help="Only run if the last successful backup is older than max_age_hours. Used by the catch-up scheduler."
	)
	parser.add_argument(
		'--dry-run',
		action='store_true',
		help="Show which repositories would be backed up without changing anything."
	)
	return parser.parse_args()

# --- Configuration ---

def load_config(config_path_arg: Optional[str]) -> Tuple[Dict[str, Any], pathlib.Path]:
	"""
	Loads configuration from a specified file or falls back to defaults.
	Searches the script's directory first, then the current directory.
	Returns the config dictionary and the directory used to resolve relative paths.
	"""
	config_path: Optional[pathlib.Path] = None

	if config_path_arg:
		candidate = pathlib.Path(config_path_arg).expanduser()
		if candidate.is_file():
			config_path = candidate
		else:
			logging.warning(f"Specified config file not found: {config_path_arg}")
	else:
		search_dirs: List[pathlib.Path] = []
		for directory in (pathlib.Path(__file__).resolve().parent, pathlib.Path.cwd()):
			if directory not in search_dirs:
				search_dirs.append(directory)

		for directory in search_dirs:
			matches = [directory / name for name in DEFAULT_CONFIG_PATHS if (directory / name).is_file()]
			if matches:
				if len(matches) > 1:
					logging.warning(
						f"Found multiple configuration files: {[str(p) for p in matches]}. "
						f"Using '{matches[0]}'."
					)
				config_path = matches[0]
				break

	if config_path:
		logging.info(f"Using configuration file: {config_path}")
		try:
			if config_path.suffix == ".toml":
				if tomllib is None:
					logging.error("TOML configuration requires Python 3.11 or newer. Use a .json config instead.")
					sys.exit(1)
				with open(config_path, "rb") as f:
					data = tomllib.load(f)
			elif config_path.suffix == ".json":
				with open(config_path, "r", encoding="utf-8") as f:
					data = json.load(f)
			else:
				logging.error(f"Unsupported config file extension: {config_path.suffix}")
				sys.exit(1)
		except (json.JSONDecodeError, OSError) as e:
			logging.error(f"Failed to load or parse config file {config_path}: {e}")
			sys.exit(1)
		except Exception as e:  # e.g. tomllib.TOMLDecodeError
			logging.error(f"Failed to load or parse config file {config_path}: {e}")
			sys.exit(1)

		if not isinstance(data, dict):
			logging.error(f"Config file {config_path} must contain a JSON/TOML object.")
			sys.exit(1)
		return data, config_path.parent

	logging.warning("No configuration file found. Using built-in defaults.")
	return {
		"backup_root": DEFAULT_BACKUP_ROOT,
		"github_owner": "",
		"include_forks": False,
		"repos": [],
		"sleep_seconds": DEFAULT_SLEEP_SECONDS,
		"randomize_sleep": DEFAULT_RANDOMIZE_SLEEP,
	}, pathlib.Path.cwd()

def resolve_path(raw_path: str, base_dir: pathlib.Path) -> pathlib.Path:
	"""Resolves a possibly-relative path against a base directory."""
	path = pathlib.Path(raw_path).expanduser()
	if not path.is_absolute():
		path = base_dir / path
	return path.resolve()

# --- GitHub discovery ---

def find_gh() -> Optional[str]:
	"""Locates the GitHub CLI, including paths launchd would not have in PATH."""
	for env_var in ("EVERGIT_GH", "GH_BIN"):
		candidate = os.environ.get(env_var)
		if candidate:
			path = pathlib.Path(candidate).expanduser()
			if path.is_file():
				return str(path)

	found = shutil.which("gh")
	if found:
		return found

	candidates = [
		pathlib.Path.home() / "bin" / "gh",
		pathlib.Path("/opt/homebrew/bin/gh"),
		pathlib.Path("/usr/local/bin/gh"),
		pathlib.Path("/usr/bin/gh"),
	]
	for path in candidates:
		if path.is_file():
			return str(path)
	return None

def gh_env() -> Dict[str, str]:
	"""Environment for non-interactive gh calls."""
	env = os.environ.copy()
	env.setdefault("GH_NO_UPDATE_NOTIFIER", "1")
	env.setdefault("GH_PROMPT_DISABLED", "1")
	return env

def git_env() -> Dict[str, str]:
	"""Environment for non-interactive git calls (never hang on a password prompt)."""
	env = os.environ.copy()
	env.setdefault("GIT_TERMINAL_PROMPT", "0")
	return env

def parse_owner_repo(url: str) -> Optional[Tuple[str, str]]:
	"""Extracts (owner, repo) from an HTTPS or SSH Git URL."""
	url = url.strip().rstrip("/")
	match = re.search(r'(?:[:/])([^/:]+)/([^/]+?)(?:\.git)?$', url)
	if not match:
		return None
	return match.group(1), match.group(2)

def discover_repos(owner: str, gh_bin: str, include_forks: bool, exclude: set) -> Optional[List[Dict[str, Any]]]:
	"""
	Asks GitHub for every repository owned by 'owner'.
	Returns None on failure (so the caller can fail loudly rather than silently
	backing up nothing), or a sorted list of repo dictionaries.
	"""
	command = [
		gh_bin, "repo", "list", owner,
		"--limit", "1000",
		"--json", "nameWithOwner,url,isFork,isArchived",
	]
	logging.info(f"Discovering repositories for '{owner}' via GitHub CLI...")
	try:
		result = subprocess.run(
			command,
			capture_output=True,
			text=True,
			timeout=120,
			env=gh_env()
		)
	except (OSError, subprocess.TimeoutExpired) as e:
		logging.error(f"Could not run GitHub CLI: {e}")
		return None

	if result.returncode != 0:
		logging.error(f"Could not list repositories for '{owner}': {result.stderr.strip()}")
		return None

	try:
		raw_repos = json.loads(result.stdout)
	except json.JSONDecodeError as e:
		logging.error(f"Unexpected response from GitHub CLI: {e}")
		return None

	repos: List[Dict[str, Any]] = []
	skipped_forks = 0
	for item in raw_repos:
		full_name = item.get("nameWithOwner") or ""
		if not full_name:
			continue
		if item.get("isFork") and not include_forks:
			skipped_forks += 1
			continue
		if full_name.lower() in exclude:
			logging.info(f"Excluding repository by configuration: {full_name}")
			continue

		url = item.get("url") or f"https://github.com/{full_name}"
		if not url.endswith(".git"):
			url += ".git"
		repos.append({
			"full_name": full_name,
			"url": url,
			"is_archived": bool(item.get("isArchived")),
		})

	repos.sort(key=lambda repo: repo["full_name"].lower())
	logging.info(f"Discovered {len(repos)} repositories ({skipped_forks} forks skipped).")
	return repos

def resolve_github_name(owner: str, name: str, gh_bin: str) -> Optional[str]:
	"""
	Asks GitHub for the current full name of owner/name.
	GitHub redirects renamed repositories, so this returns the new name.
	Returns None if the repository is gone or cannot be queried.
	"""
	command = [gh_bin, "api", f"repos/{owner}/{name}", "--jq", ".full_name"]
	try:
		result = subprocess.run(command, capture_output=True, text=True, timeout=60, env=gh_env())
	except (OSError, subprocess.TimeoutExpired) as e:
		logging.warning(f"Could not query GitHub for {owner}/{name}: {e}")
		return None
	if result.returncode != 0:
		return None
	full_name = result.stdout.strip()
	return full_name or None

def resolve_renames(
	owner: str,
	backup_root: pathlib.Path,
	repos: List[Dict[str, Any]],
	gh_bin: str,
	dry_run: bool
) -> None:
	"""
	If a local backup folder is no longer in GitHub's repo list, check whether
	the repository was renamed. If so, move the existing folder to the new
	name instead of cloning the whole repository again.
	"""
	owner_dir = backup_root / owner
	if not owner_dir.is_dir():
		return

	current = {repo["full_name"].lower(): repo for repo in repos}
	for entry in sorted(owner_dir.iterdir()):
		if not entry.is_dir() or entry.name.startswith("."):
			continue
		old_full_name = f"{owner}/{entry.name}"
		if old_full_name.lower() in current:
			continue
		if not is_git_repo(entry):
			continue

		logging.info(f"Local backup '{old_full_name}' is not in GitHub's repository list; checking for a rename...")
		resolved = resolve_github_name(owner, entry.name, gh_bin)
		if not resolved:
			logging.warning(f"{old_full_name} - not found on GitHub (deleted or inaccessible); leaving the local backup untouched.")
			continue
		if resolved.lower() == old_full_name.lower():
			continue

		target_repo = current.get(resolved.lower())
		if not target_repo:
			logging.warning(f"{old_full_name} - GitHub resolves this to '{resolved}', which is not in the repo list; skipping.")
			continue

		new_name = resolved.split("/", 1)[1]
		target_dir = owner_dir / new_name
		if target_dir.exists():
			logging.warning(f"{old_full_name} - would rename to '{new_name}', but that folder already exists; leaving both alone.")
			continue
		if dry_run:
			logging.info(f"[dry-run] Would rename local backup '{entry.name}' -> '{new_name}'.")
			continue

		try:
			entry.rename(target_dir)
		except OSError as e:
			logging.error(f"Could not rename '{entry}' to '{target_dir}': {e}")
			continue
		logging.info(f"Renamed local backup '{old_full_name}' -> '{resolved}'.")

		try:
			subprocess.run(
				["git", "remote", "set-url", "origin", target_repo["url"]],
				cwd=str(target_dir),
				capture_output=True,
				text=True,
				timeout=60,
				env=git_env()
			)
		except (OSError, subprocess.TimeoutExpired) as e:
			logging.warning(f"{resolved} - could not update the origin URL: {e}")

# --- Git helpers ---

def is_git_repo(path: pathlib.Path) -> bool:
	"""Checks if a directory is a valid (non-bare) Git repository."""
	if not path.is_dir():
		return False
	return (path / ".git").exists()

def has_uncommitted_changes(repo_path: pathlib.Path) -> bool:
	"""Checks if a Git repository has uncommitted changes."""
	try:
		result = subprocess.run(
			['git', 'status', '--porcelain'],
			cwd=str(repo_path),
			capture_output=True,
			text=True,
			check=True,
			timeout=120,
			env=git_env()
		)
		return bool(result.stdout.strip())
	except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
		logging.error(f"Failed to check git status in {repo_path}: {e}")
		return True  # Assume changes to be safe

def run_git_command(
	command: List[str],
	repo_path: pathlib.Path,
	repo_id: str,
	timeout: float = GIT_TIMEOUT_SECONDS
) -> None:
	"""
	Executes a Git command, logs its output, and raises CalledProcessError on failure.
	A timeout prevents a scheduled run from hanging forever on a network stall.
	"""
	logging.info(f"Running command: '{' '.join(command)}' in '{repo_path}'")
	try:
		result = subprocess.run(
			command,
			cwd=str(repo_path),
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			text=True,
			timeout=timeout,
			env=git_env()
		)
	except subprocess.TimeoutExpired:
		raise RuntimeError(f"Git command timed out after {timeout:.0f} seconds: {' '.join(command)}")

	lines = [
		line.strip()
		for line in (result.stdout or "").replace("\r", "\n").splitlines()
		if line.strip()
	]
	# Cap progress output so a long clone does not flood the log.
	for line in lines[-500:]:
		logging.info(f"  ({repo_id}) {line}")

	if result.returncode != 0:
		raise subprocess.CalledProcessError(
			returncode=result.returncode,
			cmd=command,
			stderr="\n".join(lines[-40:])
		)

def backup_repo(repo: Dict[str, Any], backup_root: pathlib.Path) -> bool:
	"""
	Clones or updates a single repository.
	Returns True on success, False on failure.
	Updates all remote branches and tags, then fast-forwards the working tree
	only when it is clean.
	"""
	parsed = parse_owner_repo(repo["url"])
	if not parsed:
		logging.error(f"Could not parse owner and repository name from URL: {repo['url']}")
		return False

	owner, repo_name = parsed
	repo_path = backup_root / owner / repo_name
	repo_id = f"{owner}/{repo_name}"
	logging.info(f"Processing repository: {repo_id}")

	try:
		if not repo_path.exists():
			logging.info(f"Cloning {repo_id}...")
			repo_path.parent.mkdir(parents=True, exist_ok=True)
			run_git_command(
				['git', 'clone', '--progress', repo['url'], str(repo_path)],
				repo_path.parent,
				repo_id
			)
			logging.info(f"{repo_id} - cloned successfully.")
			return True

		if not is_git_repo(repo_path):
			logging.warning(f"{repo_id} - directory exists but is not a valid git repository, skipping.")
			return False

		# Fetch every branch and tag. This keeps the backup complete even when
		# the working tree cannot be updated (dirty checkout, diverged branch).
		logging.info(f"Fetching all branches and tags for {repo_id}...")
		run_git_command(
			['git', 'fetch', '--prune', '--force', '--tags', 'origin', '+refs/heads/*:refs/remotes/origin/*'],
			repo_path,
			repo_id,
			timeout=1800.0
		)

		if has_uncommitted_changes(repo_path):
			logging.info(f"{repo_id} - has local changes; remote refs are backed up, working tree left untouched.")
		else:
			try:
				run_git_command(
					['git', 'merge', '--ff-only', '@{upstream}'],
					repo_path,
					repo_id,
					timeout=600.0
				)
			except subprocess.CalledProcessError as e:
				error_message = e.stderr.strip() if e.stderr else "(no error message captured)"
				logging.warning(
					f"{repo_id} - remote refs backed up, but the working tree could not fast-forward: {error_message}"
				)

		logging.info(f"{repo_id} - backup updated successfully.")
		return True

	except subprocess.CalledProcessError as e:
		error_message = e.stderr.strip() if e.stderr else "(no error message captured)"
		logging.error(f"{repo_id} - operation failed: {error_message}")
		return False
	except Exception as e:
		logging.error(f"{repo_id} - an unexpected error occurred: {e}")
		return False

# --- Runtime state ---

def is_writable(path: pathlib.Path) -> bool:
	"""
	Checks if a path is writable by creating and removing a temporary file.
	More reliable than os.access, which ignores macOS TCC restrictions.
	"""
	try:
		parent = path
		while not parent.exists():
			if parent.parent == parent:
				return False
			parent = parent.parent

		if not os.access(parent, os.W_OK):
			logging.error(f"'{parent}' is not writable (permission bits).")
			return False

		temp_file = parent / f".tmp_write_test_{os.getpid()}"
		try:
			temp_file.touch()
			temp_file.unlink()
		except OSError as e:
			logging.error(
				f"Write test failed for '{parent}': {e} "
				f"[errno {e.errno}]. If this only happens under launchd, "
				f"grant Full Disk Access to the Python binary."
			)
			return False
		return True
	except OSError as e:
		logging.error(f"Could not verify writability of '{path}': {e} [errno {e.errno}]")
		return False

def prepare_backup_root(path: pathlib.Path) -> bool:
	"""
	Creates the backup root if needed and verifies it is writable.
	Fails loudly instead of falling back to a relative path, which under
	launchd resolves to read-only '/' and silently loses every backup.
	"""
	try:
		path.mkdir(parents=True, exist_ok=True)
	except OSError as e:
		logging.error(f"Backup root '{path}' is not available: {e}")
		return False

	if not is_writable(path):
		logging.error(f"Backup root '{path}' is not writable. Is the backup drive mounted?")
		return False

	logging.info(f"Using backup root: {path}")
	return True

def acquire_lock() -> Optional[IO[str]]:
	"""Prevents the daily run and the catch-up run from overlapping."""
	if fcntl is None:
		# Locking is best-effort on platforms without fcntl (e.g. Windows).
		return open(os.devnull, "w")

	lock_path = pathlib.Path.home() / ".evergit.lock"
	try:
		handle = open(lock_path, "w")
		fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
		return handle
	except (BlockingIOError, OSError) as e:
		logging.info(f"Another evergit run is already in progress; exiting. ({e})")
		return None

def is_due(backup_root: pathlib.Path, max_age_hours: float) -> bool:
	"""True if the last successful backup is older than max_age_hours."""
	marker = backup_root / STATE_FILENAME
	try:
		age_seconds = time.time() - marker.stat().st_mtime
	except OSError:
		return True
	return age_seconds >= (max_age_hours * 3600.0)

def mark_successful_run(backup_root: pathlib.Path) -> None:
	"""Records the completion time so --if-due can skip redundant runs."""
	marker = backup_root / STATE_FILENAME
	try:
		marker.touch()
	except OSError as e:
		logging.warning(f"Could not write the run marker {marker}: {e}")

# --- Main ---

def main() -> int:
	"""Main entry point for the script."""
	args = parse_arguments()
	setup_logging(args.log_file)

	logging.info("Starting backup run")

	config, config_dir = load_config(args.config)

	raw_backup_root = args.backup_root or config.get("backup_root") or DEFAULT_BACKUP_ROOT
	backup_root = resolve_path(str(raw_backup_root), config_dir)
	owner = str(config.get("github_owner") or "").strip()
	include_forks = bool(config.get("include_forks", False))
	exclude = {str(name).strip().lower() for name in (config.get("exclude_repos") or [])}
	sleep_seconds = (
		args.sleep_seconds
		if args.sleep_seconds is not None
		else float(config.get("sleep_seconds", DEFAULT_SLEEP_SECONDS))
	)
	randomize_sleep = not args.no_randomize_sleep and bool(config.get("randomize_sleep", DEFAULT_RANDOMIZE_SLEEP))
	max_age_hours = float(config.get("max_age_hours", DEFAULT_MAX_AGE_HOURS))

	lock = acquire_lock()
	if lock is None:
		return 0

	if args.if_due and not is_due(backup_root, max_age_hours):
		logging.info(f"Last successful backup is less than {max_age_hours:g} hours old; nothing to do (--if-due).")
		return 0

	if not prepare_backup_root(backup_root):
		return 1

	# Discover repositories from GitHub. Abort loudly instead of backing up
	# nothing if discovery fails.
	repos: List[Dict[str, Any]] = []
	manual_repos = config.get("repos") or []
	gh_bin = find_gh()

	if owner:
		if not gh_bin:
			logging.error(
				"GitHub CLI ('gh') was not found, so repositories cannot be discovered. "
				"Install gh or set EVERGIT_GH to its full path."
			)
			return 1

		discovered = discover_repos(owner, gh_bin, include_forks, exclude)
		if discovered is None:
			logging.error("Repository discovery failed; aborting so this is not mistaken for a successful backup.")
			return 1
		if not discovered:
			logging.error(
				f"GitHub returned no repositories for '{owner}'. "
				"Run 'gh auth status' to check authentication, or set github_owner in the config."
			)
			return 1
		repos.extend(discovered)
	else:
		logging.warning("No 'github_owner' configured; using only the repositories listed in the config.")

	# Add any manually listed repositories (e.g. repos owned by another account).
	known_names = {repo["full_name"].lower() for repo in repos}
	for raw_url in manual_repos:
		parsed = parse_owner_repo(str(raw_url))
		if not parsed:
			logging.warning(f"Could not parse repository URL from config: {raw_url}")
			continue
		full_name = f"{parsed[0]}/{parsed[1]}"
		if full_name.lower() in known_names:
			continue
		if full_name.lower() in exclude:
			continue
		url = str(raw_url).strip().rstrip("/")
		if not url.endswith(".git"):
			url += ".git"
		repos.append({"full_name": full_name, "url": url, "is_archived": False})
		known_names.add(full_name.lower())
		logging.info(f"Added repository from config: {full_name}")

	if not repos:
		logging.error("No repositories to back up. Check the configuration.")
		return 1

	if owner:
		resolve_renames(owner, backup_root, repos, gh_bin, args.dry_run)

	repos.sort(key=lambda repo: repo["full_name"].lower())

	successes = 0
	failures = 0

	for index, repo in enumerate(repos):
		if args.dry_run:
			logging.info(f"[dry-run] Would back up {repo['full_name']} ({repo['url']})")
			successes += 1
		elif backup_repo(repo, backup_root):
			successes += 1
		else:
			failures += 1

		if index < len(repos) - 1 and not args.dry_run:
			delay = sleep_seconds
			if randomize_sleep:
				delay = random.uniform(delay * 0.5, delay * 1.5)
			if delay > 0:
				logging.info(f"Sleeping for {delay:.2f} seconds...")
				time.sleep(delay)

	logging.info(f"Backup run complete: {successes} succeeded, {failures} failed.")

	# Record the run so --if-due does not retry for hours. A total outage
	# (zero successes) leaves no marker, so the catch-up run tries again.
	if not args.dry_run and successes > 0:
		mark_successful_run(backup_root)

	return 1 if failures > 0 else 0

if __name__ == "__main__":
	sys.exit(main())
