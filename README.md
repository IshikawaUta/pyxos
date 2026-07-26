# Pyxos

[Bahasa Indonesia](README_ID.md)

[![CI](https://github.com/IshikawaUta/pyxos/actions/workflows/ci.yml/badge.svg)](https://github.com/IshikawaUta/pyxos/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

CLI tool for project management — push, pull, list, update, and delete projects between local, MongoDB Atlas, and Cloudinary or Backblaze B2.

## Prerequisites

- Python 3.10+
- MongoDB Atlas cluster ([free tier M0](https://www.mongodb.com/atlas))
- **One** storage backend:
  - Cloudinary ([free tier](https://cloudinary.com)) — max **10 MB** per file
  - Backblaze B2 ([free 10 GB](https://www.backblaze.com/b2/cloud-storage.html)) — **no file size limit**, great for large projects

## Installation

### pipx

```bash
pipx install git+https://github.com/IshikawaUta/pyxos.git
```

### From source

```bash
git clone https://github.com/IshikawaUta/pyxos.git
cd pyxos
pipx install .
```

Or via virtual environment:

```bash
git clone https://github.com/IshikawaUta/pyxos.git
cd pyxos
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Verify:

```bash
pyxos --version
```

## Configuration

### Method 1: Interactive (Recommended)

```bash
pyxos init
```

The prompts will ask for:
1. **Storage backend** — `cloudinary` or `b2`
2. **MongoDB Atlas URI** (hidden input)
3. Storage credentials based on choice (Cloudinary: Cloud Name, API Key, API Secret; B2: Bucket Name, Application Key ID, Application Key)

### Method 2: Environment Variables

**Cloudinary:**
```bash
export PYXOS_STORAGE_TYPE=cloudinary
export PYXOS_MONGODB_URI="mongodb+srv://user:pass@cluster.mongodb.net/"
export PYXOS_CLOUDINARY_CLOUD_NAME="my-cloud"
export PYXOS_CLOUDINARY_API_KEY="123456789"
export PYXOS_CLOUDINARY_API_SECRET="abc123xyz"
```

**Backblaze B2:**
```bash
export PYXOS_STORAGE_TYPE=b2
export PYXOS_MONGODB_URI="mongodb+srv://user:pass@cluster.mongodb.net/"
export PYXOS_B2_APPLICATION_KEY_ID="your_key_id"
export PYXOS_B2_APPLICATION_KEY="your_app_key"
export PYXOS_B2_BUCKET_NAME="my-bucket"
```

### Method 3: `.env` File

Create a `.env` file in your working directory (see `.env.example`):

**Cloudinary:**
```
storage_type=cloudinary
mongodb_uri=mongodb+srv://user:pass@cluster.mongodb.net/
cloudinary_cloud_name=my-cloud
cloudinary_api_key=123456789
cloudinary_api_secret=abc123xyz
```

**B2:**
```
storage_type=b2
mongodb_uri=mongodb+srv://user:pass@cluster.mongodb.net/
b2_application_key_id=your_key_id
b2_application_key=your_app_key
b2_bucket_name=my-bucket
```

### Configuration Priority

1. `~/.pyxos/config.json` (from `pyxos init`)
2. `.env` file in working directory
3. Environment variables (`PYXOS_*`)

### Verify Connection

```bash
pyxos check
```

### View Configuration

```bash
pyxos config show
```

### Reset Configuration

```bash
pyxos config reset
```

### Switch Storage Backend

Run `pyxos init` again to switch between Cloudinary and B2. Previously pushed projects remain pullable (each stores `storage_type` in database metadata).

---

## Architecture

```
Pyxos/
├── .github/
│   └── workflows/
│       └── ci.yml
├── .env.example
├── .gitignore
├── LICENSE
├── README.md
├── README_ID.md
├── pyproject.toml
├── pyxos/
│   ├── __init__.py
│   ├── cli.py          # CLI commands (Click + Rich)
│   ├── config.py       # Configuration, archive .zip, filter patterns
│   ├── database.py     # MongoDB Atlas CRUD
│   ├── storage.py      # Cloudinary + B2 upload/download/delete/resume
│   ├── cache.py        # Local cache for offline listing
│   ├── crypto.py       # AES-256-CBC encrypt/decrypt (streaming)
│   ├── parallel.py     # Parallel upload/download with chunking
│   ├── gui/
│   │   ├── __init__.py
│   │   └── main.py          # Desktop GUI (PySide6)
│   └── web/
│       ├── __init__.py
│       ├── app.py            # Web dashboard (optional)
│       ├── static/
│       │   └── style.css
│       └── templates/
│           ├── base.html
│           ├── config.html
│           ├── error.html
│           ├── index.html
│           ├── project_detail.html
│           ├── projects.html
│           └── stats.html
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_cache.py
    ├── test_cli.py
    ├── test_config.py
    ├── test_crypto.py
    ├── test_database.py
    ├── test_gui.py
    ├── test_parallel.py
    ├── test_storage.py
    ├── test_web.py
    └── test_web_routes.py
```

### Data Flow

```
push:  [local] ──zip──▶ [tmp] ──upload──▶ [Cloudinary / B2]
                          │                        │
                          └──metadata─────────────▶ [MongoDB Atlas]

pull:  [MongoDB Atlas] ──metadata──▶ [query]
                          │
                          └──public_id──▶ [Cloudinary / B2] ──download──▶ [local]
```

---

## Commands

### `pyxos push` — Upload project to cloud

```bash
pyxos push [PATH] [OPTIONS]
```

| Flag | Short | Description |
|---|---|---|
| `--name` | `-n` | Project name (default: directory name) |
| `--description` | `-d` | Project description |
| `--tags` | `-t` | Comma-separated tags, e.g. `"python,web,api"` |
| `--version` | `-v` | Project version (default: `1.0.0`) |
| `--force` | `-f` | Overwrite existing project |
| `--dry-run` | | Preview files to package without uploading |
| `--no-confirm-size` | | Skip confirmation for projects >50 MB |
| `--exclude` | `-e` | Extra patterns to exclude (repeatable) |
| `--include` | `-i` | Force-include patterns despite exclusions (repeatable) |
| `--encrypt` | `-E` | Encrypt archive before uploading (prompts for password) |
| `--password` | | Encryption password (or set `PYXOS_PASSWORD` env var) |
| `--compress-level` | | Compression level 0-9 (default: 6) |
| `--no-hooks` | | Skip pre/post push hooks |

> **Note:** Cloudinary free tier limits uploads to **10 MB**. Projects >10 MB are automatically rejected with a clear message. Use B2 storage for large projects.

**Examples:**

```bash
# Push current directory
pyxos push .

# Push with full metadata
pyxos push ./myapp -n MyApp -d "A web application" -t "python,flask" -v 2.0.0

# Overwrite existing project
pyxos push . --force

# Preview without uploading
pyxos push . --dry-run

# Exclude log files, except error.log
pyxos push . -e "*.log" -i "error.log"
```

### `pyxos pull` — Download project from cloud

```bash
pyxos pull [QUERY] [OPTIONS]
```

`QUERY` can be a project name or ID. If omitted, an interactive list is shown.

| Flag | Short | Description |
|---|---|---|
| `--output` | `-o` | Output directory (default: `.`) |
| `--force` | `-f` | Overwrite if directory already exists |
| `--no-hooks` | | Skip pre/post pull hooks |

**Examples:**

```bash
# Choose from interactive list
pyxos pull

# Pull by name
pyxos pull MyApp

# Pull to specific directory
pyxos pull MyApp -o ~/projects

# Overwrite if exists
pyxos pull MyApp --force
```

### `pyxos list` — List all projects

```bash
pyxos list [OPTIONS]
```

| Flag | Short | Description |
|---|---|---|
| `--search` | `-s` | Search by name or description (case-insensitive) |
| `--tag` | `-t` | Filter by tag (repeatable for AND) |
| `--page` | `-p` | Page number (default: 1) |
| `--per-page` | | Results per page (default: 20) |
| `--json` | | Output as JSON |
| `--no-cache` | | Skip cache, force fresh data from database |
| `--offline` | | Use cache only, no database connection |

**Examples:**

```bash
# All projects
pyxos list

# Search projects containing "api"
pyxos list -s api

# Filter by specific tags
pyxos list -t python -t web

# Next page
pyxos list -p 2

# JSON output for scripting
pyxos list --json
```

### `pyxos info` — Project details

```bash
pyxos info [QUERY] [OPTIONS]
```

Displays detailed information about a project, including name, size, versions, tags, storage backend, and timestamps.

| Flag | Description |
|------|-------------|
| `--no-cache` | Skip cache, force fresh data from database |

Displays: ID, version, description, tags, file count, size, local path, storage URL, created_at, updated_at.

```bash
# Interactive selection
pyxos info

# By name
pyxos info MyApp
```

### `pyxos update` — Update metadata or re-upload

```bash
pyxos update QUERY [OPTIONS]
```

| Flag | Short | Description |
|---|---|---|
| `--name` | `-n` | New name |
| `--description` | `-d` | New description |
| `--tags` | `-t` | New tags |
| `--version` | `-v` | New version |
| `--reupload` | `-r` | Re-upload files from stored local path |

**Examples:**

```bash
# Update metadata only
pyxos update MyApp -d "New description" -v 2.1.0

# Update metadata + re-upload files
pyxos update MyApp -r -v 2.1.0

# Rename project
pyxos update MyApp -n NewName
```

### `pyxos delete` — Delete project

```bash
pyxos delete [QUERY] [OPTIONS]
```

| Flag | Short | Description |
|---|---|---|
| `--yes` | `-y` | Skip confirmation |
| `--all` | | Delete ALL projects (requires `--yes`) |

Deletes from storage **and** MongoDB Atlas.

```bash
# Interactive
pyxos delete

# Delete by name
pyxos delete MyApp

# No confirmation
pyxos delete MyApp -y

# Delete all projects
pyxos delete --all --yes
```

### `pyxos open` — Open in browser

```bash
pyxos open [QUERY]
```

Opens the project's storage URL in the default browser.

### `pyxos check` — Check connections

```bash
pyxos check
```

Verifies MongoDB Atlas and storage backend (Cloudinary/B2) connections with a loading spinner.

### `pyxos diff` — Compare local vs remote

```bash
pyxos diff [QUERY] [OPTIONS]
```

Shows file differences between local project directory and remote version.

| Flag | Short | Description |
|---|---|---|
| `--output` | `-o` | Override local project path |

> **Encryption:** Use `--encrypt` on `push` to encrypt the archive before uploading. Encrypted projects are automatically detected and decrypted on `pull` (prompts for password).

### `pyxos share` — Generate share link

```bash
pyxos share [QUERY] [OPTIONS]
```

Generates a temporary download link for a project.

| Flag | Short | Description |
|---|---|---|
| `--expires` | `-e` | Expiration time in hours (default: 24) |
| `--copy` | | Copy URL to clipboard |

### `pyxos stats` — Show project statistics

```bash
pyxos stats [OPTIONS]
```

Displays aggregate statistics: total projects, total size, storage backends used, tags distribution.

### `pyxos rollback` — Revert to previous version

```bash
pyxos rollback QUERY [OPTIONS]
```

Rollback to a previous version of a project stored in the version history.

| Flag | Short | Description |
|---|---|---|
| `--version` | `-v` | Rollback to specific version ID |

### `pyxos clone` — Clone a project

```bash
pyxos clone QUERY [OPTIONS]
```

Clone/download a remote project to a new local directory.

| Flag | Short | Description |
|---|---|---|
| `--output` | `-o` | Output directory |

### `pyxos tags` — Manage project tags

```bash
pyxos tags [COMMAND]
```

Manage tags on projects. Subcommands:

| Command | Description |
|---------|-------------|
| `pyxos tags add <QUERY> <TAG...>` | Add one or more tags to a project |
| `pyxos tags remove <QUERY> <TAG...>` | Remove one or more tags from a project |
| `pyxos tags set <QUERY> <TAG...>` | Replace all tags on a project |
| `pyxos tags list [QUERY]` | List tags (all projects or specific project) |

### `pyxos config` — Manage configuration

```bash
pyxos config [COMMAND]
```

Subcommands:
- `pyxos config show` — Display current config (secrets masked)
- `pyxos config reset` — Reset configuration

### `pyxos export` — Export database

```bash
pyxos export [QUERY] [OPTIONS]
```

Export project metadata to JSON.

| Flag | Short | Description |
|---|---|---|
| `--all` | | Export all projects |
| `--output` | `-o` | Output file path |
| `--format` | `-f` | Output format: `json` or `csv` |

### `pyxos import` — Import database

```bash
pyxos import FILE [OPTIONS]
```

Import projects from a JSON export file.

| Flag | Description |
|------|-------------|
| `--merge` | Overwrite existing projects by name |

### `pyxos watch` — Watch and auto-push

```bash
pyxos watch [PATH] [OPTIONS]
```

Watch a directory for changes and automatically push. Uses efficient `watchfiles` if installed, falls back to polling.

| Flag | Short | Description |
|---|---|---|
| `--interval` | `-i` | Debounce interval in seconds (default: 2.0) |
| `--name` | `-n` | Project name |

### `pyxos web` — Web dashboard

```bash
pyxos web [OPTIONS]
```

Start a local web dashboard to browse and manage projects.

| Flag | Short | Description |
|---|---|---|
| `--host` | | Listen host (default: 127.0.0.1) |
| `--port` | `-p` | Listen port (default: 8765) |

### `pyxos completion` — Shell completion

```bash
pyxos completion [SHELL]
```

Generate shell completion script. Supports `bash`, `zsh`, `fish`.

```bash
# Zsh
eval "$(pyxos completion zsh)"

# Bash
eval "$(pyxos completion bash)"
```

---

## File Exclusion

### Default Exclude Patterns

When running `push`, the following files/directories are automatically excluded:

```
.git, .gitignore
__pycache__, *.pyc, *.pyo
.venv, venv, .env
node_modules
.idea, .vscode
__MACOSX
.DS_Store
*.egg-info
dist, build
.pyxosignore
```

### `.pyxosignore`

Create a `.pyxosignore` file in the project root to add custom patterns:

```
# .pyxosignore - custom exclusions
*.log
temp/
secrets.json
```

Lines starting with `#` are comments.

### CLI Override

```bash
# Add exclude patterns via CLI
pyxos push . -e "*.md" -e "docs/"

# Force-include files matching exclude patterns
pyxos push . -e "*.py" -i "main.py"
```

---

## Database Schema

Collection: `pyxos.projects`

| Field | Type | Description |
|---|---|---|
| `_id` | ObjectId | Auto-generated |
| `name` | String | Project name (unique) |
| `description` | String | Project description |
| `tags` | Array[String] | Tags for filtering |
| `version` | String | Project version |
| `storage_type` | String | `cloudinary` or `b2` |
| `storage_url` | String | Download URL from storage |
| `storage_public_id` | String | Public ID / file path (Cloudinary: `pyxos/{name}`, B2: `pyxos/{name}.zip`) |
| `local_path` | String | Local path at push time |
| `file_size` | Int | Archive size in bytes |
| `file_count` | Int | Number of files in archive |
| `encrypted` | Bool | Whether archive is encrypted |
| `exclude_patterns` | Array[String] | Exclude patterns used during push |
| `created_at` | DateTime | Creation time (UTC) |
| `updated_at` | DateTime | Last update time (UTC) |

> **Note:** The fields `cloudinary_url` and `cloudinary_public_id` are still supported as fallback for older projects (backward compatible). New projects are written with `storage_url` / `storage_public_id`.

---

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| [click](https://click.palletsprojects.com) | >=8.1 | CLI framework |
| [rich](https://rich.readthedocs.io) | >=13 | Tables, panels, progress bars, spinners |
| [pymongo[srv]](https://pymongo.readthedocs.io) | >=4.6 | MongoDB driver (+SRV support) |
| [cloudinary](https://cloudinary.com/documentation/python_integration) | >=1.36 | Cloudinary SDK |
| [b2sdk](https://github.com/Backblaze/b2-sdk-python) | >=2.0 | Backblaze B2 SDK |
| [cryptography](https://cryptography.io) | >=41 | AES-256-CBC encryption/decryption |

### Optional Dependencies

| Extra | Package | Purpose |
|---|---|---|
| `[web]` | [fenrir-framework](https://github.com/IshikawaUta/fenrir) | Web dashboard (`pyxos web`) |
| `[watch]` | [watchfiles](https://github.com/samuelcolvin/watchfiles) | Efficient file watching (`pyxos watch`) |
| `[gui]` | [PySide6](https://wiki.qt.io/Qt_for_Python) | Desktop GUI (`pyxos gui`) |
| `[clipboard]` | [pyperclip](https://github.com/asweigart/pyperclip) | Clipboard support (`pyxos share --copy`) |

Install with extras:

```bash
pip install "pyxos[web,watch]"
```

---

## Error Handling

Pyxos uses `sys.excepthook` to catch unhandled exceptions and display user-friendly messages without tracebacks:

- `KeyboardInterrupt` (Ctrl+C) → "Cancelled."
- `click.Abort` → silent exit
- `click.UsageError` → red error message
- HTTP errors (4xx/5xx) → descriptive message with status code
- Storage errors → specific backend error message
- Database errors → connection and query error messages
- Other exceptions → red error message with details

---

## Progress Indicators

- **Upload**: progress bar with transfer speed (B2: parallel chunked upload for files >50 MB)
- **Download**: progress bar with chunked resume support (both Cloudinary and B2)
- **Encrypt/Decrypt**: streaming processing — memory-efficient for any file size
- **List/Check**: spinner loading during database queries
- **Size warning**: confirmation prompt for projects >50 MB
- **Watch mode**: live display with debounce-based auto-push

---

## Cache

Pyxos maintains a local cache of the project list for offline use:

```bash
# Force fresh data + invalidate stale cache
pyxos list --no-cache

# List using cache only (offline mode)
pyxos list --offline

# Info with fresh data
pyxos info MyApp --no-cache
```

Cache is stored at `~/.pyxos/cache.json` with a default freshness window. The `--no-cache` flag both skips loading cache AND invalidates the existing cache file.

---

## Web Dashboard

```bash
# Install with optional web dependency
pip install "pyxos[web]"

# Start dashboard
pyxos web --host 0.0.0.0 --port 8765
```

Browse projects, view statistics, and manage metadata from a web interface. Built with Fenrir.

---

## Desktop GUI

```bash
# Install with optional gui dependency
pip install "pyxos[gui]"

# Launch
pyxos gui
```

Native cross-platform desktop application built with PySide6 (Qt). Features:

- **Config dialog** on first launch — set storage & MongoDB
- **Dashboard** — overview with stats + recent projects
- **Projects** — searchable, paginated table with detail view
- **Push** — file picker + metadata form + progress
- **Pull** — search by name/ID + download + extract
- **Stats** — aggregate metrics with storage breakdown
- **Config** — view/mask/reset configuration
- **Dark theme** — native Qt Fusion style

Works on Windows, macOS, and Linux.

---

## License

MIT — see [LICENSE](LICENSE) file.
