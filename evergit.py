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
		# Search for and prioritize default config files in the script's directory.
		script_dir = pathlib.Path(__file__).resolve().parent
		found_configs = [
			path for default_filename in DEFAULT_CONFIG_PATHS
			if (path := script_dir / default_filename).is_file()
		]

		if len(found_configs) > 1:
			logging.warning(
				f"Found multiple configuration files: {[str(p) for p in found_configs]}. "
				f"Using '{found_configs[0]}'."
			)

		if found_configs:
			config_path = found_configs[0]
			logging.info(f"Using configuration file: {config_path}")

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

def run_git_command(command: List[str], repo_path: Union[str, pathlib.Path], repo_id: str) -> None:
	"""
	Executes a Git command and streams its output to the logger.
	Raises CalledProcessError on failure.
	"""
	logging.info(f"Running command: '{' '.join(command)}' in '{repo_path}'")
	process = subprocess.Popen(
		command,
		cwd=repo_path,
		stdout=subprocess.PIPE,
		stderr=subprocess.STDOUT, # Merge stderr into stdout
		text=True,
		bufsize=1 # Line-buffered
	)

	output_lines = []
	# Stream the output line by line
	if process.stdout:
		for line in iter(process.stdout.readline, ''):
			line = line.strip()
			if line:
				logging.info(f"  ({repo_id}) {line}")
				output_lines.append(line)
		process.stdout.close()

	process.wait()

	if process.returncode != 0:
		# Reconstruct stderr for the exception from the captured output.
		stderr_output = "\n".join(output_lines)
		raise subprocess.CalledProcessError(
			returncode=process.returncode,
			cmd=command,
			stderr=stderr_output
		)

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
			run_git_command(
				['git', 'clone', '--progress', repo_url, str(repo_path)],
				repo_path.parent,
				repo_id
			)
			logging.info(f"{repo_id} - cloned successfully.")
		else:
			if not is_git_repo(repo_path):
				logging.warning(f"{repo_id} - directory exists but is not a valid git repository, skipping.")
				return

			logging.info(f"Checking for uncommitted changes in {repo_id}...")
			if has_uncommitted_changes(repo_path):
				logging.warning(f"{repo_id} - has uncommitted changes, skipping.")
				return

			logging.info(f"Pulling updates for {repo_id}...")
			run_git_command(
				['git', 'pull', '--progress'],
				repo_path,
				repo_id
			)
			logging.info(f"{repo_id} - pulled successfully.")

	except subprocess.CalledProcessError as e:
		error_message = e.stderr.strip() if e.stderr else "(no error message captured)"
		logging.error(f"{repo_id} - operation failed: {error_message}")
	except Exception as e:
		logging.error(f"{repo_id} - an unexpected error occurred: {e}")

def is_writable(path: pathlib.Path) -> bool:
	"""
	Checks if a path is writable by trying to create a temporary file.
	This is more reliable than os.access across different platforms.
	"""
	try:
		# Find the first existing parent directory to test writability.
		parent = path
		while not parent.exists():
			# If we go all the way to the root and it doesn't exist, it's not writable.
			if parent.parent == parent:
				return False
			parent = parent.parent
		
		# Now that we have an existing directory, check if we can write to it.
		# A simple os.access check is a good first step.
		if not os.access(parent, os.W_OK):
			return False
			
		# To be absolutely sure, attempt to create a temporary file.
		temp_file = parent / f".tmp_write_test_{os.getpid()}"
		temp_file.touch()
		temp_file.unlink()
		return True
	except (IOError, OSError):
		return False

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

	# Fallback to default if the configured backup_root is inaccessible
	if backup_root != DEFAULT_BACKUP_ROOT and not is_writable(backup_root_path):
		logging.warning(
			f"Backup root '{backup_root}' is not a writable directory or cannot be created. "
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
