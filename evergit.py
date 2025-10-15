#!/usr/bin/env python3
# evergit.py
# A modular, single-file _skeleton_ for backing up GitHub repositories.
# MIT License - © Michael Thomason 2025

import argparse
import json
import logging
import pathlib
import random
import re
import subprocess
import sys
import time
import tomllib
from typing import Dict, Any, List, Optional, Union

# --- Constants ---
DEFAULT_CONFIG_PATHS: List[str] = ["evergit.toml", "evergit.json"]
DEFAULT_BACKUP_ROOT: str = "./evergit_backups"
DEFAULT_REPOS: List[str] = [
	"https://github.com/github/docs.git",
	"https://github.com/mthomason/ObjectiveMorality.git",
]
DEFAULT_SLEEP_SECONDS: float = 3.0
DEFAULT_RANDOMIZE_SLEEP: bool = True

# --- Main Application Logic ---

def setup_logging(log_file: Optional[str] = None) -> None:
	"""Configures the logging format and destination."""
	handlers: List[Union[logging.FileHandler, logging.StreamHandler]] = [logging.StreamHandler()]
	if log_file:
		try:
			handlers.append(logging.FileHandler(log_file))
		except IOError as e:
			logging.error(f"Could not open log file {log_file}: {e}")
			sys.exit(1)

	logging.basicConfig(
		level=logging.INFO,
		format='[%(asctime)s] %(levelname)-7s %(message)s',
		datefmt='%Y-%m-%d %H:%M:%S',
		handlers=handlers
	)

def parse_arguments() -> argparse.Namespace:
	"""Parses command-line arguments."""
	parser = argparse.ArgumentParser(description="A cross-platform, non-destructive GitHub repository backup script.")
	parser.add_argument(
		'--config',
		type=str,
		default=None,
		help=f"Path to a TOML or JSON configuration file. Defaults to searching for {', '.join(DEFAULT_CONFIG_PATHS)} in the current directory."
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
		help="Override the sleep duration in seconds."
	)
	parser.add_argument(
		'--no-randomize-sleep',
		action='store_true',
		help="Disable sleep randomization if specified."
	)
	return parser.parse_args()

def load_config(config_path_arg: Optional[str]) -> Dict[str, Any]:
	"""
	Loads configuration from a specified file or falls back to defaults.
	Searches for default config files in the script's directory.
	"""
	config_path: Optional[pathlib.Path] = None

	if config_path_arg:
		path = pathlib.Path(config_path_arg)
		if path.is_file():
			config_path = path
		else:
			logging.warning(f"Specified config file not found: {config_path_arg}")
	else:
		# Search for default config files in the same directory as the script
		script_dir = pathlib.Path(__file__).resolve().parent
		for default_filename in DEFAULT_CONFIG_PATHS:
			path = script_dir / default_filename
			if path.is_file():
				config_path = path
				logging.info(f"Found configuration file: {config_path}")
				break

	if config_path:
		try:
			with open(config_path, "rb") as f:
				if config_path.suffix == ".toml":
					return tomllib.load(f)
				elif config_path.suffix == ".json":
					return json.load(f)
				else:
					logging.error(f"Unsupported config file extension: {config_path.suffix}")
					sys.exit(1)
		except (tomllib.TOMLDecodeError, json.JSONDecodeError, IOError) as e:
			logging.error(f"Failed to load or parse config file {config_path}: {e}")
			sys.exit(1)

	logging.warning("No configuration file found. Using hardcoded default values.")
	return {
		"backup_root": DEFAULT_BACKUP_ROOT,
		"sleep_seconds": DEFAULT_SLEEP_SECONDS,
		"randomize_sleep": DEFAULT_RANDOMIZE_SLEEP,
		"repos": DEFAULT_REPOS,
	}

def get_repo_path_from_url(repo_url: str, backup_root: pathlib.Path) -> Optional[pathlib.Path]:
	"""
	Parses a Git URL to create a unique, structured path for the backup.
	e.g., https://github.com/owner/repo.git -> backup_root/owner/repo
	"""
	match = re.search(r'(?:[:/])([^/:]+)/([^/]+?)(?:\.git)?$', repo_url)
	if not match:
		logging.error(f"Could not parse repository owner and name from URL: {repo_url}")
		return None
	
	owner, repo_name = match.groups()
	return backup_root / owner / repo_name

def is_git_repo(path: pathlib.Path) -> bool:
	"""Checks if a directory is a valid (non-bare) Git repository."""
	if not path.is_dir():
		return False
	# A standard working copy will have a .git directory inside it.
	return (path / ".git").is_dir()

def has_uncommitted_changes(repo_path: pathlib.Path) -> bool:
	"""Checks if a Git repository has uncommitted changes."""
	try:
		result = subprocess.run(
			['git', 'status', '--porcelain'],
			cwd=repo_path,
			capture_output=True,
			text=True,
			check=True
		)
		return bool(result.stdout.strip())
	except subprocess.CalledProcessError as e:
		logging.error(f"Failed to check git status in {repo_path}: {e.stderr}")
		return True # Assume changes to be safe

def backup_repo(repo_url: str, backup_root: pathlib.Path) -> None:
	"""
	Clones or pulls a single repository in a non-destructive way.
	"""
	repo_path = get_repo_path_from_url(repo_url, backup_root)
	if not repo_path:
		return

	repo_id = f"{repo_path.parent.name}/{repo_path.name}"
	logging.info(f"Processing repository: {repo_id}")

	try:
		if not repo_path.exists():
			logging.info(f"Cloning {repo_id}...")
			repo_path.parent.mkdir(parents=True, exist_ok=True)
			subprocess.run(
				['git', 'clone', repo_url, str(repo_path)],
				capture_output=True, text=True, check=True
			)
			logging.info(f"{repo_id} - cloned successfully.")
		else:
			if not is_git_repo(repo_path):
				logging.warning(f"{repo_id} - directory exists but is not a valid git repository, skipping.")
				return

			if has_uncommitted_changes(repo_path):
				logging.warning(f"{repo_id} - has uncommitted changes, skipping.")
				return

			logging.info(f"Pulling updates for {repo_id}...")
			subprocess.run(
				['git', 'pull'],
				cwd=repo_path,
				capture_output=True, text=True, check=True
			)
			logging.info(f"{repo_id} - pulled successfully.")

	except subprocess.CalledProcessError as e:
		error_message = e.stderr.strip()
		logging.error(f"{repo_id} - operation failed: {error_message}")
	except Exception as e:
		logging.error(f"{repo_id} - an unexpected error occurred: {e}")


def main() -> None:
	"""Main entry point for the script."""
	args = parse_arguments()
	setup_logging(args.log_file)
	
	logging.info("Starting backup run")
	
	config = load_config(args.config)
	
	backup_root = args.backup_root or config.get("backup_root", DEFAULT_BACKUP_ROOT)
	sleep_seconds = args.sleep_seconds if args.sleep_seconds is not None else float(config.get("sleep_seconds", DEFAULT_SLEEP_SECONDS))
	randomize_sleep = not args.no_randomize_sleep and config.get("randomize_sleep", DEFAULT_RANDOMIZE_SLEEP)

	backup_root_path = pathlib.Path(backup_root).expanduser()

	# Fallback to default if the parent of the configured backup_root is inaccessible
	if backup_root != DEFAULT_BACKUP_ROOT and not backup_root_path.parent.is_dir():
		logging.warning(
			f"Parent directory of '{backup_root}' is not accessible. "
			f"Falling back to default location: '{DEFAULT_BACKUP_ROOT}'"
		)
		backup_root_path = pathlib.Path(DEFAULT_BACKUP_ROOT).expanduser()

	repos = config.get("repos", [])
	
	if not repos:
		logging.warning("No repositories listed in configuration. Nothing to do.")
		logging.info("Backup run complete")
		return

	for i, repo_url in enumerate(repos):
		backup_repo(repo_url, backup_root_path)
		
		if i < len(repos) - 1:
			delay = sleep_seconds
			if randomize_sleep:
				delay = random.uniform(delay * 0.5, delay * 1.5)
			
			if delay > 0:
				logging.info(f"Sleeping for {delay:.2f} seconds...")
				time.sleep(delay)

	logging.info("Backup run complete")

if __name__ == "__main__":
	main()
