# evergit

**Backup your GitHub repositories.**

This is a simple script that clones and updates local backups of GitHub repositories on a scheduled basis.

## Overview

**evergit** is a lightweight Python utility for maintaining up-to-date local backups of your GitHub repositories.
It can be run manually or scheduled (for example, via `cron`) to ensure you always have current local mirrors of your repositories — even if GitHub or your account becomes unavailable.

## Features

*	Automatically clones and updates multiple GitHub repositories
*	Stores complete git history locally (not just snapshots)
*	Simple configuration using a TOML or JSON file
*	Supports private repositories via SSH or personal access tokens
*	Works well with cron or other schedulers
*	Minimal dependencies — pure Python and the `git` CLI

## Requirements

*	Python 3.13 or higher
*	`git` command-line tool installed and available in `PATH`
*	(Optional) GitHub personal access token for private repositories

## Installation

Clone the repository:

```bash
git clone https://github.com/mthomason/evergit.git
cd evergit
```

## Configuration

Create a configuration file (e.g., `evergit.toml` or `evergit.json`) in the same directory as the script.

If no configuration file is found, the script will fall back to a default list of repositories.

### TOML Example (`evergit.toml`)
```toml
backup_root = "./evergit_backups"
sleep_seconds = 3.0
randomize_sleep = true
repos = [
	"https://github.com/github/docs.git",
	"https://github.com/mthomason/ObjectiveMorality.git",
]
```

### JSON Example (`evergit.json`)
```json
{
	"backup_root": "./evergit_backups",
	"sleep_seconds": 3.0,
	"randomize_sleep": true,
	"repos": [
		"https://github.com/github/docs.git",
		"https://github.com/mthomason/ObjectiveMorality.git"
	]
}
```

## Usage

Run manually:

```bash
python evergit.py --config evergit.toml
```

Example cron job (runs daily at 3 AM):

```bash
0 3 * * * /usr/bin/python3 /path/to/evergit.py --config /path/to/evergit.toml >> /path/to/log.txt 2>&1
```

### Example Output
```
[2025-10-14 03:00:00] INFO    Starting backup run
[2025-10-14 03:00:01] INFO    Processing repository: github/docs
[2025-10-14 03:00:05] INFO    github/docs - pulled successfully.
[2025-10-14 03:00:10] INFO    Processing repository: mthomason/ObjectiveMorality
[2025-10-14 03:00:15] WARNING mthomason/ObjectiveMorality - has uncommitted changes, skipping.
[2025-10-14 03:00:15] INFO    Backup run complete
```

## License

MIT License © 2025 Michael Thomason

## About Scheduling

For most users, **cron** remains the simplest and most reliable way to schedule this script on Linux or macOS.

Alternatives:

*	**systemd timers** — better for logging and retries on Linux systems
*	**Windows Task Scheduler** — native equivalent for Windows
*	**Docker/Containers** — run via a lightweight scheduler process or GitHub Actions

If you just want hourly or daily backups, cron is perfectly fine.
