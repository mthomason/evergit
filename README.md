# evergit

**A simple script that clones and updates local backups of GitHub repositories on a scheduled basis.**

## Overview

**evergit** is a lightweight Python utility for maintaining up-to-date local backups of your GitHub repositories.
It can be run manually or scheduled (for example, via `cron`) to ensure you always have current local mirrors of your repositories — even if GitHub or your account becomes unavailable.

## Features

* Automatically clones and updates multiple GitHub repositories
* Stores complete git history locally (not just snapshots)
* Simple configuration using a text or YAML file
* Supports private repositories via SSH or personal access tokens
* Works well with cron or other schedulers
* Minimal dependencies — pure Python and the `git` CLI

## Requirements

* Python 3.8 or higher
* `git` command-line tool installed and available in `PATH`
* (Optional) GitHub personal access token for private repositories

## Installation

Clone the repository:

```bash
git clone https://github.com/yourusername/evergit.git
cd evergit
pip install -r requirements.txt
```

Or, if published later:

```bash
pip install evergit
```

## Configuration

Create a configuration file (e.g., `config.yaml`):

```yaml
backup_root: /path/to/backup/folder
repos:
  - https://github.com/username/repo1.git
  - git@github.com:username/repo2.git
```

## Usage

Run manually:

```bash
python evergit.py --config config.yaml
```

Example cron job (runs daily at 3 AM):

```bash
0 3 * * * /usr/bin/python3 /path/to/evergit.py --config /path/to/config.yaml >> /path/to/log.txt 2>&1
```

Example output:

```
[2025-10-14 03:00:01] Updating repo: repo1
Already up to date.
[2025-10-14 03:00:05] Updating repo: repo2
Pulling changes...
Done.
```

## License

MIT License © 2025 Michael Thomason

## About Scheduling

For most users, **cron** remains the simplest and most reliable way to schedule this script on Linux or macOS.

Alternatives:

* **systemd timers** — better for logging and retries on Linux systems
* **Windows Task Scheduler** — native equivalent for Windows
* **Docker/Containers** — run via a lightweight scheduler process or GitHub Actions

If you just want hourly or daily backups, cron is perfectly fine.
