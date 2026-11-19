# evergit

**Backup your GitHub repositories.**

This is a simple script that clones and updates local backups of GitHub repositories on a scheduled basis.

## Overview

**evergit** is a lightweight Python utility for maintaining up-to-date local backups of your GitHub repositories.
It can be run manually or scheduled (for example, via `cron`) to ensure you always have current local mirrors of your repositories — even if GitHub or your account becomes unavailable.

## Features

*	Discovers every repository in your GitHub account automatically — no hardcoded list to maintain
*	Follows repository renames, moving the existing local backup instead of re-cloning it
*	Backs up every branch and tag, not just the default branch
*	Stores complete git history locally (not just snapshots)
*	Non-destructive: clones and fast-forwards, and never overwrites local changes
*	Optionally includes or excludes forks and individual repositories
*	Simple configuration using a TOML or JSON file
*	Supports private repositories via your existing git credentials
*	Works well with cron, launchd, systemd timers, or Task Scheduler
*	Minimal dependencies — pure Python, the `git` CLI, and the GitHub CLI for discovery

## Requirements

*	Python 3.11 or higher (3.13 recommended)
*	`git` command-line tool installed and available in `PATH`
*	[GitHub CLI](https://cli.github.com/) (`gh`), authenticated with `gh auth login`, for repository discovery

## Installation

Clone the repository:

```bash
git clone https://github.com/mthomason/evergit.git
cd evergit
```

## Configuration

Create a configuration file (e.g., `evergit.toml` or `evergit.json`) in the same directory as the script.

Repositories are discovered automatically from `github_owner`. The optional `repos` list adds
repositories that discovery would not return (for example, a repository owned by someone else).

### TOML Example (`evergit.toml`)
```toml
backup_root = "./evergit_backups"
github_owner = "mthomason"
include_forks = false
exclude_repos = []
repos = [
	"https://github.com/github/docs.git",
]
sleep_seconds = 3.0
randomize_sleep = true
max_age_hours = 23.0
```

### JSON Example (`evergit.json`)
```json
{
	"backup_root": "./evergit_backups",
	"github_owner": "mthomason",
	"include_forks": false,
	"exclude_repos": [],
	"repos": [],
	"sleep_seconds": 3.0,
	"randomize_sleep": true,
	"max_age_hours": 23.0
}
```

### Configuration keys

| Key | Default | Meaning |
| --- | --- | --- |
| `backup_root` | `~/evergit_backups` | Where backups are stored. Relative paths resolve against the config file's directory. |
| `github_owner` | *(none)* | GitHub user or organization whose repositories are discovered. |
| `include_forks` | `false` | Set to `true` to back up forks as well as your own repositories. |
| `exclude_repos` | `[]` | Full names such as `"owner/name"` to skip. |
| `repos` | `[]` | Extra repository URLs to back up in addition to discovered ones. |
| `sleep_seconds` | `3.0` | Delay between repositories, to reduce load. |
| `randomize_sleep` | `true` | Randomize the delay between 50% and 150% of `sleep_seconds`. |
| `max_age_hours` | `23.0` | With `--if-due`, skip the run if the last successful backup is newer than this. |

If no configuration file is found, there is no `github_owner` and no repository list, so the
script exits with an error rather than silently backing up nothing.

## Usage

Run manually:

```bash
python3 evergit.py --config evergit.json
```

Preview what would happen without changing anything:

```bash
python3 evergit.py --dry-run
```

Only run if the last successful backup is more than `max_age_hours` old:

```bash
python3 evergit.py --if-due
```

Example cron job (runs daily at 3 AM):

```bash
0 3 * * * /usr/bin/python3 /path/to/evergit.py --config /path/to/evergit.toml >> /path/to/log.txt 2>&1
```

### Example Output
```
[2025-10-14 03:00:00] INFO    Starting backup run
[2025-10-14 03:00:01] INFO    Using configuration file: /path/to/evergit.json
[2025-10-14 03:00:01] INFO    Using backup root: /path/to/evergit_backups
[2025-10-14 03:00:02] INFO    Discovering repositories for 'mthomason' via GitHub CLI...
[2025-10-14 03:00:03] INFO    Discovered 40 repositories (18 forks skipped).
[2025-10-14 03:00:04] INFO    Processing repository: github/docs
[2025-10-14 03:00:08] INFO    github/docs - backup updated successfully.
[2025-10-14 03:00:12] INFO    Processing repository: mthomason/ObjectiveMorality
[2025-10-14 03:00:13] INFO    mthomason/ObjectiveMorality - has local changes; remote refs are backed up, working tree left untouched.
[2025-10-14 03:00:13] INFO    Backup run complete: 40 succeeded, 0 failed.
```

If the backup destination is unavailable, the script logs an error and exits with status 1.
It never falls back to a relative path, which would write somewhere unexpected (and under
launchd is typically a read-only filesystem).

## License

MIT License © 2025 Michael Thomason

## About Scheduling

For most users, **cron** remains the simplest and most reliable way to schedule this script on Linux or macOS.

Alternatives:

*	**systemd timers** — better for logging and retries on Linux systems
*	**Windows Task Scheduler** — native equivalent for Windows
*	**Docker/Containers** — run via a lightweight scheduler process or GitHub Actions

If you just want hourly or daily backups, cron is perfectly fine.

### Catch-up runs

If the backup drive is not mounted when a scheduled run fires, the run exits with an error
instead of writing somewhere unintended. To retry automatically, schedule `--if-due` more
frequently (for example every two hours); it performs a full run only when the last successful
backup is older than `max_age_hours`, and exits immediately otherwise.

### macOS privacy permissions

macOS requires explicit permission for a process to read and write removable volumes. A
scheduled job (launchd agent, cron, or an app) needs **Removable Volumes** access for the
Python binary it runs. Grant it in **System Settings → Privacy & Security → Files and Folders**
(or add the Python app to **Full Disk Access**). Without it, the script logs
`Operation not permitted [errno 1]` for the backup root and exits with status 1.

This permission is tied to the specific Python installation. After upgrading Python, the
scheduled job may lose access; re-grant it to the new binary (or keep using a Python version
that already has access).
