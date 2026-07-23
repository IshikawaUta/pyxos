import os
import json
import zipfile
import fnmatch
from pathlib import Path

CONFIG_DIR = Path.home() / ".pyxos"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_EXCLUDED_PATTERNS = [
    ".git", ".gitignore",
    "__pycache__", "*.pyc", "*.pyo",
    ".venv", "venv", ".env",
    "node_modules",
    ".idea", ".vscode",
    "__MACOSX",
    ".DS_Store",
    "*.egg-info",
    "dist", "build",
    ".pyxosignore",
]


def ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


_config_source = "none"


def get_config_source():
    return _config_source


def load_config():
    global _config_source
    env_file = Path(".env")

    if CONFIG_FILE.exists():
        _config_source = "config.json"
        with open(CONFIG_FILE) as f:
            config = json.load(f)
    elif env_file.exists():
        _config_source = ".env"
        config = {}
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key = key.strip().lower()
                value = value.strip().strip('"').strip("'")
                config[key] = value
    else:
        _config_source = "none"
        config = {}

    for key in (
        "storage_type",
        "mongodb_uri",
        "cloudinary_cloud_name", "cloudinary_api_key", "cloudinary_api_secret",
        "b2_application_key_id", "b2_application_key", "b2_bucket_name",
    ):
        env_val = os.environ.get(f"PYXOS_{key.upper()}")
        if env_val:
            config[key] = env_val

    return config


def save_config(config):
    ensure_config_dir()
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def delete_config():
    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()
        return True
    return False


def build_exclude_patterns(project_path, extra_excludes=None, extra_includes=None):
    patterns = list(DEFAULT_EXCLUDED_PATTERNS)

    ignore_file = Path(project_path) / ".pyxosignore"
    if ignore_file.exists():
        for line in ignore_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)

    if extra_excludes:
        for pat in extra_excludes:
            if pat not in patterns:
                patterns.append(pat)

    includes = list(extra_includes) if extra_includes else []
    return patterns, includes


def should_exclude(path_name, patterns, includes=None):
    if includes:
        for inc in includes:
            if fnmatch.fnmatch(path_name, inc):
                return False
    for pat in patterns:
        if fnmatch.fnmatch(path_name, pat):
            return True
    return False


def _path_parts_excluded(rel_path, patterns, includes=None):
    parts = rel_path.split(os.sep)
    for part in parts:
        if part and should_exclude(part, patterns, includes):
            return True
    return False


def get_project_name(path):
    return Path(path).resolve().name


def get_archive_file_list(project_path, extra_excludes=None, extra_includes=None):
    project_path = Path(project_path).resolve()
    patterns, includes = build_exclude_patterns(project_path, extra_excludes, extra_includes)
    files = []
    total_size = 0

    for entry in sorted(project_path.rglob("*")):
        if entry.is_symlink():
            continue
        if entry.is_file():
            rel = str(entry.relative_to(project_path))
            if _path_parts_excluded(rel, patterns, includes):
                continue
            size = entry.stat().st_size
            files.append((rel, size))
            total_size += size

    return files, total_size


def count_archive_files(project_path, extra_excludes=None, extra_includes=None):
    files, total_size = get_archive_file_list(project_path, extra_excludes, extra_includes)
    return len(files), total_size


def make_archive(project_path, output_path, extra_excludes=None, extra_includes=None):
    project_path = Path(project_path).resolve()
    archive_path = Path(str(output_path.with_suffix("")) + ".zip")

    files_list, _ = get_archive_file_list(project_path, extra_excludes, extra_includes)
    with zipfile.ZipFile(str(archive_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for file_rel, _ in files_list:
            full_path = project_path / file_rel
            zf.write(str(full_path), file_rel)

    return archive_path
