import os
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import click
import cloudinary.exceptions
from rich import print as rprint
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

_open = open  # save builtin before @main.command("open") shadows it
from bson.errors import InvalidId

from .cache import invalidate_cache, load_cache, save_cache
from .config import (
    build_exclude_patterns,
    count_archive_files,
    delete_config,
    get_archive_file_list,
    get_config_source,
    get_project_name,
    load_config,
    make_archive,
    save_config,
)
from .crypto import decrypt_archive, encrypt_archive
from .database import Database
from .storage import (
    delete_project as cloud_delete,
)
from .storage import (
    download_project as cloud_download,
)
from .storage import (
    generate_share_link,
    init_storage,
    ping_storage,
)
from .storage import (
    upload_project as cloud_upload,
)

console = Console()


def get_db():
    cfg = load_config()
    uri = cfg.get("mongodb_uri")
    if not uri:
        rprint("[red]✗ MongoDB URI not configured. Run 'pyxos init' first.[/red]")
        raise SystemExit(1)
    return Database(uri)


def require_storage(cfg):
    st = cfg.get("storage_type", "cloudinary")
    if st == "cloudinary":
        required = ["cloudinary_cloud_name", "cloudinary_api_key", "cloudinary_api_secret"]
    else:
        required = ["b2_application_key_id", "b2_application_key", "b2_bucket_name"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        rprint(f"[red]✗ Missing {st} config: {', '.join(missing)}. Run 'pyxos init' first.[/red]")
        raise SystemExit(1)
    init_storage(cfg)


def _resolve_project(db, query):
    try:
        project = db.get_project(project_id=query)
    except InvalidId:
        project = None
    if not project:
        project = db.get_project(name=query)
    return project


def _format_size(size):
    if size is None:
        return "-"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / 1024:.1f} KB"


def _error_handler(exc_type, exc_val, exc_tb):
    if issubclass(exc_type, click.Abort):
        sys.exit(0)
    if issubclass(exc_type, click.exceptions.UsageError):
        rprint(f"[red]✗ {exc_val}[/red]")
        sys.exit(1)
    if issubclass(exc_type, KeyboardInterrupt):
        rprint("\n[yellow]Cancelled.[/yellow]")
        sys.exit(0)
    rprint(f"[red]✗ Unexpected error: {exc_val}[/red]")
    sys.exit(1)


LOGO = r"""
╔═══════════════════════════════════════════════╗
║                                               ║
║   ██████╗ ██╗   ██╗██╗  ██╗ ██████╗ ███████╗  ║
║   ██╔══██╗╚██╗ ██╔╝╚██╗██╔╝██╔═══██╗██╔════╝  ║
║   ██████╔╝ ╚████╔╝  ╚███╔╝ ██║   ██║███████╗  ║
║   ██╔═══╝   ╚██╔╝   ██╔██╗ ██║   ██║╚════██║  ║
║   ██║        ██║   ██╔╝ ██╗╚██████╔╝███████║  ║
║   ╚═╝        ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝  ║
║                                               ║
║          ~  project management cli  ~         ║
║                                               ║
╚═══════════════════════════════════════════════╝"""

sys.excepthook = _error_handler


@click.group(invoke_without_command=True)
@click.version_option("1.0.0")
@click.pass_context
def main(ctx):
    """Pyxos - Project Management CLI.

    Push/pull projects to/from MongoDB Atlas and Cloudinary/B2.
    """
    if "_PYXOS_COMPLETE" in os.environ:
        return
    if len(sys.argv) > 1 and sys.argv[1] == "gui":
        try:
            from pyxos.gui.main import gui_launch

            _ = gui_launch
        except ImportError:
            rprint("[red]✗ Optional dependency 'PySide6' is not installed.[/red]")
            rprint("[yellow]Install it with:[/yellow]", end=" ")
            click.echo('pip install "pyxos[gui]"')
            sys.exit(1)

        import subprocess as _sp2

        proc = _sp2.run(
            [sys.executable, "-c", "from pyxos.gui.main import gui_launch; gui_launch()"],
            stderr=_sp2.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            err = proc.stderr.strip()
            if err:
                rprint(f"[red]GUI error:[/red] {err[:500]}")
        sys.exit(0)
    rprint(LOGO)

# ── init ──────────────────────────────────────────────────────────────────────

@main.command()
@click.option("--storage-type", type=click.Choice(["cloudinary", "b2"]))
@click.option("--mongodb-uri", hide_input=True)
@click.option("--cloudinary-cloud-name", default="")
@click.option("--cloudinary-api-key", default="")
@click.option("--cloudinary-api-secret", default="")
@click.option("--b2-application-key-id", default="")
@click.option("--b2-application-key", default="")
@click.option("--b2-bucket-name", default="")
@click.option("--from", "from_project", help="Project name or ID to clone configuration from")
@click.option("--output", "-o", default=".", help="Output directory for cloned project")
def init(storage_type, mongodb_uri, cloudinary_cloud_name, cloudinary_api_key, cloudinary_api_secret,
         b2_application_key_id, b2_application_key, b2_bucket_name, from_project, output):
    """Initialize Pyxos configuration."""
    if from_project:
        mongodb_uri = mongodb_uri or click.prompt("MongoDB Atlas URI", hide_input=True)

        db = Database(mongodb_uri)
        with console.status("[cyan]Connecting to MongoDB...[/cyan]"):
            mongo_ok = db.check_connection()
        if not mongo_ok:
            rprint("[red]✗ Could not connect to MongoDB Atlas.[/red]")
            db.close()
            return

        project = _resolve_project(db, from_project)
        if not project:
            rprint(f"[red]✗ Project '{from_project}' not found in database.[/red]")
            db.close()
            return

        project_name = project["name"]
        proj_storage_type = project.get("storage_type", "cloudinary")
        rprint(f"[cyan]Found project: {project_name}[/cyan]")
        rprint(f"  Version: {project.get('version', '-')}")
        rprint(f"  Storage: {proj_storage_type}")
        rprint(f"  Size:    {_format_size(project.get('file_size', 0))}")
        rprint(f"  Files:   {project.get('file_count', '-')}")

        cfg = load_config()
        if not cfg.get("storage_type"):
            cfg["storage_type"] = proj_storage_type

        if cfg.get("storage_type") == "cloudinary":
            if not cfg.get("cloudinary_cloud_name"):
                cfg["cloudinary_cloud_name"] = cloudinary_cloud_name or click.prompt("Cloudinary Cloud Name")
            if not cfg.get("cloudinary_api_key"):
                cfg["cloudinary_api_key"] = cloudinary_api_key or click.prompt("Cloudinary API Key", hide_input=True)
            if not cfg.get("cloudinary_api_secret"):
                cfg["cloudinary_api_secret"] = cloudinary_api_secret or click.prompt("Cloudinary API Secret", hide_input=True)
        else:
            if not cfg.get("b2_application_key_id"):
                cfg["b2_application_key_id"] = b2_application_key_id or click.prompt("B2 Application Key ID", hide_input=True)
            if not cfg.get("b2_application_key"):
                cfg["b2_application_key"] = b2_application_key or click.prompt("B2 Application Key", hide_input=True)
            if not cfg.get("b2_bucket_name"):
                cfg["b2_bucket_name"] = b2_bucket_name or click.prompt("B2 Bucket Name")

        cfg["mongodb_uri"] = mongodb_uri
        save_config(cfg)
        rprint(f"[green]✓ Configuration saved to ~/.pyxos/config.json (storage: {cfg['storage_type']})[/green]")

        try:
            init_storage(cfg)
            if not ping_storage():
                rprint(f"[yellow]⚠ Could not connect to {cfg['storage_type'].upper()}.[/yellow]")
        except ValueError as e:
            rprint(f"[red]✗ {e}[/red]")

        public_id = project.get("storage_public_id") or project.get("cloudinary_public_id")
        if not public_id:
            rprint("[red]✗ No storage public_id found for this project.[/red]")
            db.close()
            return

        rprint(f"[cyan]Cloning '{project_name}' to {output}...[/cyan]")
        out_dir = Path(output) / project_name
        if out_dir.exists():
            counter = 1
            while out_dir.exists():
                out_dir = Path(output) / f"{project_name} ({counter})"
                counter += 1

        tmpdir = Path(tempfile.mkdtemp())
        try:
            archive_path = cloud_download(public_id, tmpdir)
            rprint("[cyan]Extracting...[/cyan]")
            shutil.unpack_archive(str(archive_path), str(out_dir))
            rprint(f"[bold green]✓ Project '{project_name}' cloned to {out_dir}[/bold green]")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        db.close()
        return

    storage_type = storage_type or click.prompt("Storage backend (cloudinary/b2)", type=click.Choice(["cloudinary", "b2"]))
    mongodb_uri = mongodb_uri or click.prompt("MongoDB Atlas URI", hide_input=True)

    if storage_type == "cloudinary":
        cloudinary_cloud_name = cloudinary_cloud_name or click.prompt("Cloudinary Cloud Name")
        cloudinary_api_key = cloudinary_api_key or click.prompt("Cloudinary API Key", hide_input=True)
        cloudinary_api_secret = cloudinary_api_secret or click.prompt("Cloudinary API Secret", hide_input=True)
    else:
        b2_application_key_id = b2_application_key_id or click.prompt("B2 Application Key ID", hide_input=True)
        b2_application_key = b2_application_key or click.prompt("B2 Application Key", hide_input=True)
        b2_bucket_name = b2_bucket_name or click.prompt("B2 Bucket Name")

    cfg = {
        "storage_type": storage_type,
        "mongodb_uri": mongodb_uri,
    }

    if storage_type == "cloudinary":
        cfg.update({
            "cloudinary_cloud_name": cloudinary_cloud_name,
            "cloudinary_api_key": cloudinary_api_key,
            "cloudinary_api_secret": cloudinary_api_secret,
        })
    else:
        cfg.update({
            "b2_application_key_id": b2_application_key_id,
            "b2_application_key": b2_application_key,
            "b2_bucket_name": b2_bucket_name,
        })

    save_config(cfg)
    rprint(f"[green]✓ Configuration saved to ~/.pyxos/config.json (storage: {storage_type})[/green]")

    with console.status("[cyan]Testing MongoDB connection...[/cyan]"):
        db = Database(mongodb_uri)
        mongo_ok = db.check_connection()
        db.close()

    if mongo_ok:
        rprint("[green]✓ MongoDB Atlas connected successfully[/green]")
    else:
        rprint("[yellow]⚠ Could not connect to MongoDB Atlas. Check your URI.[/yellow]")

    try:
        init_storage(cfg)
        if ping_storage():
            rprint(f"[green]✓ {storage_type.upper()} connected successfully[/green]")
        else:
            rprint(f"[yellow]⚠ Could not connect to {storage_type.upper()}. Check your credentials.[/yellow]")
    except ValueError as e:
        rprint(f"[red]✗ {e}[/red]")


# ── push ──────────────────────────────────────────────────────────────────────

SIZE_WARNING_THRESHOLD = 50 * 1024 * 1024  # 50 MB


def _run_hook(hook_path):
    """Run a hook script if it exists. Returns True if hook ran successfully."""
    hook = Path(hook_path)
    if not hook.exists():
        return True
    rprint(f"[cyan]Running hook: {hook.name}[/cyan]")
    try:
        result = subprocess.run([str(hook)], capture_output=False, shell=False, check=False)
        if result.returncode != 0:
            rprint(f"[yellow]⚠ Hook '{hook.name}' exited with code {result.returncode}[/yellow]")
            return False
        return True
    except OSError as e:
        rprint(f"[yellow]⚠ Could not run hook '{hook.name}': {e}[/yellow]")
        return False


@main.command()
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option("--name", "-n", help="Project name (defaults to directory name)")
@click.option("--description", "-d", default="", help="Project description")
@click.option("--tags", "-t", help="Comma-separated tags")
@click.option("--version", "-v", default="1.0.0", help="Project version")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing project")
@click.option("--dry-run", is_flag=True, help="Show what would be packaged without uploading")
@click.option("--no-confirm-size", is_flag=True, help="Skip size confirmation for large projects")
@click.option("--exclude", "-e", "extra_excludes", multiple=True, help="Extra patterns to exclude (repeatable)")
@click.option("--include", "-i", "extra_includes", multiple=True, help="Patterns to include despite exclusions (repeatable)")
@click.option("--encrypt", "-E", is_flag=True, help="Encrypt archive with AES-256-CBC before upload")
@click.option("--password", "password_opt", help="Encryption password (or set PYXOS_PASSWORD env var)")
@click.option("--compress-level", type=click.IntRange(0, 9), default=6, help="Compression level 0-9 (default: 6)")
@click.option("--no-hooks", is_flag=True, help="Skip pre/post push hooks")
def push(path, name, description, tags, version, force, dry_run, no_confirm_size, extra_excludes, extra_includes, encrypt, password_opt, compress_level, no_hooks):
    """Push a local project to MongoDB Atlas & Cloudinary."""
    path = Path(path).resolve()
    project_name = name or get_project_name(path)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    excl = list(extra_excludes) if extra_excludes else None
    incl = list(extra_includes) if extra_includes else None

    if encrypt:
        password = password_opt or os.environ.get("PYXOS_PASSWORD") or click.prompt("Encryption password", hide_input=True, confirmation_prompt=True)
    else:
        password = None

    file_count, total_size = count_archive_files(path, excl, incl)
    total_size_mb = total_size / (1024 * 1024)

    rprint(f"[cyan]Project: {project_name}[/cyan]")
    rprint(f"[cyan]Files to package: {file_count} ({_format_size(total_size)})[/cyan]")

    if dry_run:
        rprint("\n[cyan]Files that would be included:[/cyan]")
        files, _ = get_archive_file_list(path, excl, incl)
        for fpath, fsize in files[:30]:
            rprint(f"  {fpath} ({_format_size(fsize)})")
        if len(files) > 30:
            rprint(f"  ... and {len(files) - 30} more files")
        excl_pats, inc_pats = build_exclude_patterns(path, excl, incl)
        if excl_pats:
            rprint(f"\n[dim]Exclude: {', '.join(excl_pats)}[/dim]")
        if inc_pats:
            rprint(f"[dim]Include:  {', '.join(inc_pats)}[/dim]")
        rprint("\n[yellow]Dry run — nothing uploaded.[/yellow]")
        return

    if total_size > SIZE_WARNING_THRESHOLD and not no_confirm_size:
        threshold_mb = SIZE_WARNING_THRESHOLD / (1024 * 1024)
        if click.confirm(f"[yellow]Project is {total_size_mb:.1f} MB (threshold: {threshold_mb:.0f} MB). Continue?[/yellow]", default=False) is not True:
            rprint("[yellow]Cancelled.[/yellow]")
            return

    if not no_hooks:
        for hook_name in (".pyxos-pre-push.sh", ".pyxos-pre-push"):
            _run_hook(path / hook_name)

    cfg = load_config()
    require_storage(cfg)
    db = get_db()

    existing = db.get_project(name=project_name)
    if existing and not force:
        rprint(f"[yellow]⚠ Project '{project_name}' already exists. Use --force to overwrite.[/yellow]")
        rprint(f"   Existing version: {existing.get('version', '?')}")
        rprint(f"   Description: {existing.get('description', '-')}")
        db.close()
        return

    rprint(f"[cyan]Packaging project '{project_name}'...[/cyan]")

    tmpdir = Path(tempfile.mkdtemp())
    archive_path = tmpdir / f"{project_name}.zip"

    try:
        make_archive(path, archive_path, excl, incl, compresslevel=compress_level)
        actual_size = archive_path.stat().st_size
        rprint(f"[green]✓ Archive created ({_format_size(actual_size)})[/green]")

        upload_path = archive_path
        if encrypt:
            rprint("[cyan]Encrypting archive...[/cyan]")
            enc_path = encrypt_archive(archive_path, password)
            rprint(f"[green]✓ Encrypted ({_format_size(enc_path.stat().st_size)})[/green]")
            upload_path = enc_path

        try:
            storage_url, storage_public_id = cloud_upload(upload_path, project_name)
        except ValueError as e:
            rprint(f"[yellow]⚠ {e}[/yellow]")
            return
        except (cloudinary.exceptions.Error, RuntimeError) as e:
            rprint(f"[red]✗ Storage error: {e}[/red]")
            return

        rprint("[green]✓ Uploaded to storage[/green]")

        if existing and force:
            db.save_version(existing)
            try:
                cloud_delete(existing.get("storage_public_id") or existing.get("cloudinary_public_id"))
            except RuntimeError:
                pass
            db.delete_project(project_id=existing["_id"])

        project_id = db.create_project(
            name=project_name,
            description=description,
            tags=tag_list,
            storage_url=storage_url,
            storage_public_id=storage_public_id,
            local_path=str(path),
            file_size=actual_size,
            file_count=file_count,
            version=version,
            storage_type=cfg.get("storage_type", "cloudinary"),
            encrypted=encrypt,
        )

        rprint(f"\n[bold green]✓ Project '{project_name}' pushed successfully![/bold green]")
        rprint(f"  ID:        {project_id}")
        rprint(f"  Version:   {version}")
        rprint(f"  Files:     {file_count}")
        rprint(f"  Size:      {_format_size(actual_size)}")
        rprint(f"  URL:       {storage_url}")

        if not no_hooks:
            for hook_name in (".pyxos-post-push.sh", ".pyxos-post-push"):
                _run_hook(path / hook_name)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    db.close()


# ── pull ──────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("query", required=False)
@click.option("--output", "-o", default=".", help="Output directory")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing directory")
@click.option("--no-hooks", is_flag=True, help="Skip pre/post pull hooks")
def pull(query, output, force, no_hooks):
    """Pull a project from MongoDB Atlas & Cloudinary to local."""
    cfg = load_config()
    require_storage(cfg)
    db = get_db()

    if not no_hooks:
        cwd = Path.cwd()
        for hook_name in (".pyxos-pre-pull.sh", ".pyxos-pre-pull"):
            _run_hook(cwd / hook_name)

    if not query:
        click.echo()
        project = _select_project(db)
        if not project:
            db.close()
            return
    else:
        project = _resolve_project(db, query)
        if not project:
            rprint(f"[red]✗ Project '{query}' not found.[/red]")
            db.close()
            return

    project_name = project["name"]
    public_id = project.get("storage_public_id") or project.get("cloudinary_public_id")

    if not public_id:
        rprint("[red]✗ No storage public_id found for this project.[/red]")
        db.close()
        return

    out_dir = Path(output) / project_name
    if out_dir.exists() and not force:
        rprint(f"[red]✗ Directory '{out_dir}' already exists. Use --force to overwrite.[/red]")
        db.close()
        return

    if out_dir.exists():
        shutil.rmtree(out_dir)

    rprint(f"[cyan]Downloading '{project_name}' from storage...[/cyan]")

    tmpdir = Path(tempfile.mkdtemp())
    try:
        archive_path = cloud_download(public_id, tmpdir)

        if project.get("encrypted"):
            password = os.environ.get("PYXOS_PASSWORD") or click.prompt("Encryption password", hide_input=True)
            rprint("[cyan]Decrypting archive...[/cyan]")
            dec_path = decrypt_archive(archive_path, password)
            rprint(f"[cyan]Extracting to {out_dir}...[/cyan]")
            out_dir.mkdir(parents=True, exist_ok=True)
            shutil.unpack_archive(str(dec_path), str(out_dir))
        else:
            rprint(f"[cyan]Extracting to {out_dir}...[/cyan]")
            shutil.unpack_archive(str(archive_path), str(out_dir))

        rprint(f"[bold green]✓ Project '{project_name}' pulled to {out_dir}[/bold green]")

        if not no_hooks:
            out_dir_path = Path(out_dir)
            for hook_name in (".pyxos-post-pull.sh", ".pyxos-post-pull"):
                _run_hook(out_dir_path / hook_name)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    db.close()


# ── update ────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("query")
@click.option("--name", "-n", help="New project name")
@click.option("--description", "-d", help="New description")
@click.option("--tags", "-t", help="New comma-separated tags")
@click.option("--version", "-v", help="New version")
@click.option("--reupload", "-r", is_flag=True, help="Re-upload project files from local path")
def update(query, name, description, tags, version, reupload):
    """Update project metadata or re-upload project files."""
    cfg = load_config()
    require_storage(cfg)
    db = get_db()

    project = _resolve_project(db, query)
    if not project:
        rprint(f"[red]✗ Project '{query}' not found.[/red]")
        db.close()
        return

    updates = {}

    if name:
        existing = db.get_project(name=name)
        if existing and str(existing["_id"]) != str(project["_id"]):
            rprint(f"[red]✗ Project name '{name}' already taken.[/red]")
            db.close()
            return
        updates["name"] = name

    if description is not None:
        updates["description"] = description
    if version:
        updates["version"] = version
    if tags is not None:
        updates["tags"] = [t.strip() for t in tags.split(",") if t.strip()]

    if reupload:
        local_path = project.get("local_path")
        if not local_path or not Path(local_path).exists():
            rprint(f"[red]✗ Local path not available: {local_path}[/red]")
            db.close()
            return

        db.save_version(project)

        local_path = Path(local_path)
        refresh_name = name or project["name"]
        file_count, _ = count_archive_files(local_path)

        tmpdir = Path(tempfile.mkdtemp())
        archive_path = tmpdir / f"{refresh_name}.zip"
        try:
            rprint(f"[cyan]Re-packaging from {local_path}...[/cyan]")
            make_archive(local_path, archive_path)
            actual_size = archive_path.stat().st_size

            rprint("[cyan]Re-uploading to storage...[/cyan]")
            storage_url, storage_public_id = cloud_upload(archive_path, refresh_name)

            updates["storage_url"] = storage_url
            updates["storage_public_id"] = storage_public_id
            updates["file_size"] = actual_size
            updates["file_count"] = file_count
            rprint("[green]✓ Re-uploaded[/green]")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    if updates:
        changed = db.update_project(project["_id"], **updates)
        if changed:
            rprint(f"[bold green]✓ Project '{name or project['name']}' updated[/bold green]")
            for k, v in updates.items():
                val = v if k not in ("storage_url", "storage_public_id", "file_size", "file_count") else "..."
                rprint(f"  {k}: {val}")
        else:
            rprint("[yellow]⚠ No changes made.[/yellow]")
    else:
        rprint("[yellow]⚠ No options provided. Use --help for available options.[/yellow]")

    db.close()


# ── clone ─────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("query")
@click.option("--output", "-o", default=".", help="Output directory")
@click.option("--name", "-n", help="Project name for the cloned directory")
def clone(query, output, name):
    """Clone a project from MongoDB Atlas & Cloudinary to local.

    Downloads and extracts a project without overwriting existing directories.
    If the target directory exists, a number is appended (e.g., MyApp, MyApp (1), MyApp (2)).
    """
    cfg = load_config()
    require_storage(cfg)
    db = get_db()

    project = _resolve_project(db, query)
    if not project:
        rprint(f"[red]✗ Project '{query}' not found.[/red]")
        db.close()
        return

    project_name = project["name"]
    public_id = project.get("storage_public_id") or project.get("cloudinary_public_id")

    if not public_id:
        rprint("[red]✗ No storage public_id found for this project.[/red]")
        db.close()
        return

    dir_name = name or project_name
    out_dir = Path(output) / dir_name

    counter = 1
    while out_dir.exists():
        out_dir = Path(output) / f"{dir_name} ({counter})"
        counter += 1

    rprint(f"[cyan]Cloning '{project_name}' to {out_dir}...[/cyan]")

    tmpdir = Path(tempfile.mkdtemp())
    try:
        archive_path = cloud_download(public_id, tmpdir)
        rprint("[cyan]Extracting...[/cyan]")
        shutil.unpack_archive(str(archive_path), str(out_dir))

        rprint(f"\n[bold green]✓ Project '{project_name}' cloned to {out_dir}[/bold green]")
        rprint(f"  Files:   {project.get('file_count', '-')}")
        rprint(f"  Size:    {_format_size(project.get('file_size', 0))}")
        rprint(f"  Version: {project.get('version', '-')}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    db.close()


# ── rollback ──────────────────────────────────────────────────────────────────

@main.command()
@click.argument("query")
@click.option("--version", "-v", "version_id", help="Version ID to rollback to (from pyxos rollback list)")
def rollback(query, version_id):
    """Rollback a project to a previous version.

    Without --version, lists available versions.
    With --version, rolls back to the specified version.
    """
    cfg = load_config()
    require_storage(cfg)
    db = get_db()

    project = _resolve_project(db, query)
    if not project:
        rprint(f"[red]✗ Project '{query}' not found.[/red]")
        db.close()
        return

    versions = db.get_versions(project["_id"])

    if not versions:
        rprint(f"[yellow]No previous versions found for '{project['name']}'.[/yellow]")
        db.close()
        return

    if not version_id:
        table = Table(title=f"Available versions for '{project['name']}'")
        table.add_column("Version ID", style="cyan")
        table.add_column("Version", style="magenta")
        table.add_column("Size", style="yellow")
        table.add_column("Files")
        table.add_column("Created", style="yellow")

        for v in versions:
            created = v.get("created_at")
            created_str = created.strftime("%Y-%m-%d %H:%M UTC") if created else "-"
            table.add_row(
                str(v["_id"]),
                v.get("version", "-"),
                _format_size(v.get("file_size", 0)),
                str(v.get("file_count", "-")),
                created_str,
            )

        console.print(table)
        rprint(f"\n[dim]To rollback: pyxos rollback {query} --version <VERSION_ID>[/dim]")
        db.close()
        return

    version = db.get_version(version_id)
    if not version:
        rprint(f"[red]✗ Version '{version_id}' not found.[/red]")
        db.close()
        return

    if version["project_id"] != str(project["_id"]):
        rprint(f"[red]✗ Version '{version_id}' does not belong to project '{project['name']}'.[/red]")
        db.close()
        return

    rprint(f"[cyan]Rolling back '{project['name']}' to version {version.get('version', '-')}...[/cyan]")

    public_id = version.get("storage_public_id")
    if not public_id:
        rprint("[red]✗ No storage info for this version.[/red]")
        db.close()
        return

    local_path = project.get("local_path")
    out_dir = Path(local_path) if local_path else Path(".", project["name"])

    if out_dir.exists():
        rprint(f"[cyan]Overwriting {out_dir}...[/cyan]")
        shutil.rmtree(out_dir)

    tmpdir = Path(tempfile.mkdtemp())
    try:
        archive_path = cloud_download(public_id, tmpdir)
        shutil.unpack_archive(str(archive_path), str(out_dir))

        db.update_project(
            project["_id"],
            storage_url=version.get("storage_url", ""),
            storage_public_id=public_id,
            file_size=version.get("file_size", 0),
            file_count=version.get("file_count", 0),
            version=version.get("version", "1.0.0"),
        )

        rprint(f"[bold green]✓ Project '{project['name']}' rolled back to version {version.get('version', '-')}[/bold green]")
        rprint(f"  Extracted to: {out_dir}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    db.close()


# ── tags ───────────────────────────────────────────────────────────────────────

@main.group()
def tags():
    """Manage project tags."""


@tags.command("add")
@click.argument("query")
@click.argument("tag", nargs=-1, required=True)
def tags_add(query, tag):
    """Add tags to a project."""
    db = get_db()
    project = _resolve_project(db, query)
    if not project:
        rprint(f"[red]✗ Project '{query}' not found.[/red]")
        db.close()
        return

    existing = project.get("tags", [])
    new_tags = [t for t in tag if t not in existing]
    if not new_tags:
        rprint("[yellow]⚠ All tags already present.[/yellow]")
        db.close()
        return

    updated_tags = existing + new_tags
    db.update_project(project["_id"], tags=updated_tags)
    rprint(f"[bold green]✓ Added tags to '{project['name']}': {', '.join(new_tags)}[/bold green]")
    db.close()


@tags.command("remove")
@click.argument("query")
@click.argument("tag", nargs=-1, required=True)
def tags_remove(query, tag):
    """Remove tags from a project."""
    db = get_db()
    project = _resolve_project(db, query)
    if not project:
        rprint(f"[red]✗ Project '{query}' not found.[/red]")
        db.close()
        return

    existing = project.get("tags", [])
    tag_set = set(tag)
    updated_tags = [t for t in existing if t not in tag_set]

    removed = [t for t in tag if t in existing]
    if not removed:
        rprint("[yellow]⚠ None of the specified tags are present.[/yellow]")
        db.close()
        return

    db.update_project(project["_id"], tags=updated_tags)
    rprint(f"[bold green]✓ Removed tags from '{project['name']}': {', '.join(removed)}[/bold green]")
    db.close()


@tags.command("set")
@click.argument("query")
@click.argument("tag", nargs=-1, required=True)
def tags_set(query, tag):
    """Replace all tags on a project."""
    db = get_db()
    project = _resolve_project(db, query)
    if not project:
        rprint(f"[red]✗ Project '{query}' not found.[/red]")
        db.close()
        return

    db.update_project(project["_id"], tags=list(tag))
    rprint(f"[bold green]✓ Set tags for '{project['name']}': {', '.join(tag)}[/bold green]")
    db.close()


@tags.command("list")
@click.argument("query", required=False)
def tags_list(query):
    """List all tags on a project."""
    db = get_db()

    if not query:
        project = _select_project(db)
        if not project:
            db.close()
            return
    else:
        project = _resolve_project(db, query)
        if not project:
            rprint(f"[red]✗ Project '{query}' not found.[/red]")
            db.close()
            return

    tags_list_data = project.get("tags", [])
    if not tags_list_data:
        rprint(f"[yellow]No tags on '{project['name']}'.[/yellow]")
    else:
        rprint(f"[cyan]Tags for '{project['name']}':[/cyan]")
        for t in tags_list_data:
            rprint(f"  • {t}")
    db.close()


# ── info ──────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("query", required=False)
@click.option("--no-cache", is_flag=True, help="Skip cache, force fresh data from database")
def info(query, no_cache):
    """Show detailed information about a project."""
    cfg = load_config()
    mongodb_uri = cfg.get("mongodb_uri")
    use_cache = not no_cache
    if no_cache:
        invalidate_cache()

    if not mongodb_uri:
        if use_cache:
            projects = load_cache()
            if projects:
                if not query:
                    rprint("[yellow]DB unavailable — showing cached data.[/yellow]")
                    project = _select_project_from_list(projects)
                else:
                    project = _resolve_project_from_list(projects, query)
                    if project:
                        rprint("[yellow]DB unavailable — showing cached data.[/yellow]")
                if project:
                    _print_info_panel(project)
            else:
                rprint("[red]✗ MongoDB URI not configured. Run 'pyxos init' first.[/red]")
                raise SystemExit(1)
        else:
            rprint("[red]✗ MongoDB URI not configured. Run 'pyxos init' first.[/red]")
            raise SystemExit(1)
        return

    db = get_db()

    if not query:
        project = _select_project(db)
        if not project:
            db.close()
            return
    else:
        project = _resolve_project(db, query)
        if not project:
            rprint(f"[red]✗ Project '{query}' not found.[/red]")
            db.close()
            return

    _print_info_panel(project)
    if use_cache:
        projects, _ = db.list_projects(per_page=100)
        save_cache(projects)
    db.close()


# ── list ──────────────────────────────────────────────────────────────────────

@main.command("list")
@click.option("--search", "-s", help="Search by name or description")
@click.option("--tag", "-t", multiple=True, help="Filter by tag (repeatable)")
@click.option("--page", "-p", type=int, default=1, help="Page number")
@click.option("--per-page", type=int, default=20, help="Results per page")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.option("--no-cache", is_flag=True, help="Skip cache, force fresh data from database")
@click.option("--offline", is_flag=True, help="Use cache only, no database connection")
def list_projects(search, tag, page, per_page, json_output, no_cache, offline):
    """List all projects in MongoDB Atlas."""
    tags = list(tag) if tag else None
    use_cache = not no_cache
    if no_cache:
        invalidate_cache()
    cfg = load_config()
    mongodb_uri = cfg.get("mongodb_uri")

    if offline:
        projects = load_cache()
        if not projects:
            rprint("[yellow]No cached data available. Run 'pyxos list' online first.[/yellow]")
            return
        if search:
            search_lower = search.lower()
            projects = [p for p in projects if search_lower in (p.get("name", "") or "").lower() or search_lower in (p.get("description", "") or "").lower()]
        if tags:
            projects = [p for p in projects if all(t in (p.get("tags") or []) for t in tags)]
        total = len(projects)
        rprint("[yellow]Offline mode — showing cached data.[/yellow]")
    elif not mongodb_uri:
        if use_cache:
            projects = load_cache()
            if projects:
                if search:
                    search_lower = search.lower()
                    projects = [p for p in projects if search_lower in (p.get("name", "") or "").lower() or search_lower in (p.get("description", "") or "").lower()]
                if tags:
                    projects = [p for p in projects if all(t in (p.get("tags") or []) for t in tags)]
                total = len(projects)
                rprint("[yellow]DB unavailable — showing cached data.[/yellow]")
            else:
                rprint("[red]✗ MongoDB URI not configured. Run 'pyxos init' first.[/red]")
                raise SystemExit(1)
        else:
            rprint("[red]✗ MongoDB URI not configured. Run 'pyxos init' first.[/red]")
            raise SystemExit(1)
    else:
        db = get_db()
        with console.status("[cyan]Querying database...[/cyan]"):
            projects, total = db.list_projects(search=search, tags=tags, page=page, per_page=per_page)

        if projects and use_cache:
            all_projects, _ = db.list_projects(per_page=200)
            save_cache(all_projects)
        db.close()

    if not projects:
        rprint("[yellow]No projects found.[/yellow]")
        return

    if json_output:
        from bson import json_util
        result = {"total": total, "projects": projects}
        if offline:
            result["offline"] = True
        click.echo(json_util.dumps(result, indent=2))
        return

    total_pages = max(1, (total + per_page - 1) // per_page) if not offline else 1

    table = Table(
        title=f"Projects (page {page}/{total_pages}, total: {total})",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Name", style="green")
    table.add_column("Version", style="magenta")
    table.add_column("Description")
    table.add_column("Tags", style="blue")
    table.add_column("Size", style="yellow")
    table.add_column("Updated", style="yellow")

    for p in projects:
        tags_str = ", ".join(p.get("tags", [])) if p.get("tags") else "-"
        desc = (p.get("description") or "-")[:50]
        version = p.get("version", "-")
        updated = p.get("updated_at")
        if isinstance(updated, str):
            updated_str = updated[:16] if updated else "-"
        elif updated:
            updated_str = updated.strftime("%Y-%m-%d %H:%M")
        else:
            updated_str = "-"

        table.add_row(p["name"], version, desc, tags_str, _format_size(p.get("file_size", 0)), updated_str)

    console.print(table)

    if not offline and page < total_pages:
        rprint(f"[dim]Next page: pyxos list --page {page + 1}[/dim]")


# ── delete ────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("query", required=False)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.option("--all", "delete_all", is_flag=True, help="Delete ALL projects (requires --yes)")
def delete(query, yes, delete_all):
    """Delete a project from MongoDB Atlas & Cloudinary."""
    cfg = load_config()
    require_storage(cfg)
    db = get_db()

    if delete_all:
        if not yes:
            rprint("[red]✗ --all requires --yes confirmation[/red]")
            db.close()
            return

        all_projects, total = db.list_projects(per_page=1000)
        if total > 1000:
            page = 2
            while len(all_projects) < total:
                more, _ = db.list_projects(per_page=1000, page=page)
                if not more:
                    break
                all_projects.extend(more)
                page += 1
        if not all_projects:
            rprint("[yellow]No projects to delete.[/yellow]")
            db.close()
            return

        rprint(f"[yellow]Deleting {len(all_projects)} projects...[/yellow]")
        for p in all_projects:
            pub_id = p.get("storage_public_id") or p.get("cloudinary_public_id")
            if pub_id:
                try:
                    cloud_delete(pub_id)
                except RuntimeError:
                    pass
            db.delete_project(project_id=p["_id"])
            rprint(f"  [green]✓[/green] {p['name']}")
        rprint(f"[bold green]✓ Deleted {len(all_projects)} projects[/bold green]")
        db.close()
        return

    if not query:
        project = _select_project(db)
        if not project:
            db.close()
            return
    else:
        project = _resolve_project(db, query)
        if not project:
            rprint(f"[red]✗ Project '{query}' not found.[/red]")
            db.close()
            return

    project_name = project["name"]
    public_id = project.get("storage_public_id") or project.get("cloudinary_public_id")

    if not yes:
        confirmed = click.confirm(f"Delete project '{project_name}' from database and storage?", default=False)
        if confirmed is not True:
            rprint("[yellow]Cancelled.[/yellow]")
            db.close()
            return

    if public_id:
        try:
            cloud_delete(public_id)
            rprint("[green]✓ Deleted from storage[/green]")
        except RuntimeError as e:
            rprint(f"[yellow]⚠ Storage: {e}[/yellow]")

    db.delete_project(project_id=project["_id"])
    rprint(f"[bold green]✓ Project '{project_name}' deleted[/bold green]")
    db.close()


# ── open ──────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("query", required=False)
def open(query):
    """Open a project's storage URL in the browser."""
    db = get_db()

    if not query:
        project = _select_project(db)
        if not project:
            db.close()
            return
    else:
        project = _resolve_project(db, query)
        if not project:
            rprint(f"[red]✗ Project '{query}' not found.[/red]")
            db.close()
            return

    url = project.get("storage_url") or project.get("cloudinary_url")
    if not url:
        rprint("[red]✗ No storage URL for this project.[/red]")
        db.close()
        return

    rprint(f"[cyan]Opening {url} ...[/cyan]")
    webbrowser.open(url)
    rprint(f"[green]✓ Opened '{project['name']}' in browser[/green]")
    db.close()


# ── share ─────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("query", required=False)
@click.option("--expires", "-e", type=int, default=24, help="Expiration time in hours (default: 24)")
@click.option("--copy", "do_copy", is_flag=True, help="Copy link to clipboard")
def share(query, expires, do_copy):
    """Generate a temporary download link for a project."""
    cfg = load_config()
    require_storage(cfg)
    db = get_db()

    if not query:
        project = _select_project(db)
        if not project:
            db.close()
            return
    else:
        project = _resolve_project(db, query)
        if not project:
            rprint(f"[red]✗ Project '{query}' not found.[/red]")
            db.close()
            return

    public_id = project.get("storage_public_id") or project.get("cloudinary_public_id")
    if not public_id:
        rprint("[red]✗ No storage public_id found for this project.[/red]")
        db.close()
        return

    expiration_seconds = expires * 3600

    try:
        url, expires_at = generate_share_link(public_id, expiration_seconds)
    except Exception as e:
        rprint(f"[red]✗ Failed to generate share link: {e}[/red]")
        db.close()
        return

    local_expiry = expires_at.astimezone()
    expiry_str = local_expiry.strftime("%Y-%m-%d %H:%M:%S %Z")

    rprint(f"\n[bold cyan]Share Link for '{project['name']}'[/bold cyan]")
    rprint(f"  [dim]URL:[/dim]     {url}")
    rprint(f"  [dim]Expires:[/dim]  {expiry_str} ({expires}h)")

    if do_copy:
        try:
            import pyperclip
            pyperclip.copy(url)
            rprint("\n[green]✓ Link copied to clipboard[/green]")
        except ImportError:
            rprint("\n[yellow]⚠ pyperclip not installed. Link displayed above.[/yellow]")

    db.close()


# ── check ─────────────────────────────────────────────────────────────────────

@main.command()
def check():
    """Check database and storage connections."""
    cfg = load_config()
    uri = cfg.get("mongodb_uri")

    with console.status("[cyan]Checking MongoDB...[/cyan]"):
        if uri:
            db = Database(uri)
            mongo_ok = db.check_connection()
            db.close()
        else:
            mongo_ok = None

    if mongo_ok is True:
        rprint("[green]✓ MongoDB Atlas: Connected[/green]")
    elif mongo_ok is False:
        rprint("[red]✗ MongoDB Atlas: Connection failed[/red]")
    else:
        rprint("[yellow]⚠ MongoDB Atlas: Not configured[/yellow]")

    st = cfg.get("storage_type", "cloudinary")
    try:
        init_storage(cfg)
        if ping_storage():
            rprint(f"[green]✓ {st.upper()}: Connected[/green]")
        else:
            rprint(f"[red]✗ {st.upper()}: Connection failed (check credentials)[/red]")
    except ValueError:
        rprint(f"[yellow]⚠ {st.upper()}: Not fully configured[/yellow]")


# ── config ────────────────────────────────────────────────────────────────────

@main.group()
def config():
    """Manage Pyxos configuration."""


@config.command("show")
def config_show():
    """Show current configuration."""
    cfg = load_config()
    source = get_config_source()

    source_icon = {"config.json": "~/.pyxos/config.json", ".env": "File .env di direktori kerja", "none": "Default (kosong)"}.get(source, source)

    uri = cfg.get("mongodb_uri", "")
    st = cfg.get("storage_type", "cloudinary")
    cloud_name = cfg.get("cloudinary_cloud_name", "")
    api_key = cfg.get("cloudinary_api_key", "")
    api_secret = cfg.get("cloudinary_api_secret", "")
    b2_key_id = cfg.get("b2_application_key_id", "")
    b2_key = cfg.get("b2_application_key", "")
    b2_bucket = cfg.get("b2_bucket_name", "")

    table = Table(title="Current Configuration", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("source", source_icon)
    table.add_row("storage_type", st)
    table.add_row("mongodb_uri", uri[:30] + "..." if len(uri) > 30 else uri)
    if st == "cloudinary":
        table.add_row("cloudinary_cloud_name", cloud_name)
        table.add_row("cloudinary_api_key", api_key[:8] + "..." if api_key else "(not set)")
        table.add_row("cloudinary_api_secret", "********" if api_secret else "(not set)")
    else:
        table.add_row("b2_bucket_name", b2_bucket or "(not set)")
        table.add_row("b2_application_key_id", b2_key_id[:8] + "..." if b2_key_id else "(not set)")
        table.add_row("b2_application_key", "********" if b2_key else "(not set)")
    table.add_row("config_file", str(Path.home() / ".pyxos" / "config.json"))

    console.print(table)

    # check for env var overrides
    env_overrides = []
    for key in ("storage_type", "mongodb_uri", "cloudinary_cloud_name", "cloudinary_api_key", "cloudinary_api_secret",
                "b2_application_key_id", "b2_application_key", "b2_bucket_name"):
        if os.environ.get(f"PYXOS_{key.upper()}"):
            env_overrides.append(f"PYXOS_{key.upper()}")
    if env_overrides:
        rprint(f"[dim]Env var override: {', '.join(env_overrides)}[/dim]")


@config.command("reset")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def config_reset(yes):
    """Reset all configuration."""
    if not yes:
        if click.confirm("[yellow]Delete all Pyxos configuration? This cannot be undone.[/yellow]", default=False) is not True:
            rprint("[yellow]Cancelled.[/yellow]")
            return

    deleted_any = False
    if delete_config():
        rprint("[green]✓ Configuration file deleted (~/.pyxos/config.json)[/green]")
        deleted_any = True

    env_path = Path(".env")
    if env_path.exists():
        blacklist = ("mongodb_uri", "storage_type", "cloudinary_cloud_name", "cloudinary_api_key", "cloudinary_api_secret",
                     "b2_application_key_id", "b2_application_key", "b2_bucket_name")
        lines = env_path.read_text().splitlines()
        new_lines = []
        removed = 0
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=")[0].strip().lower()
                if key in blacklist:
                    removed += 1
                    continue
            new_lines.append(line)
        if removed:
            env_path.write_text("\n".join(new_lines) + "\n")
            rprint(f"[green]✓ Removed {removed} Pyxos keys from .env[/green]")
            deleted_any = True

    if not deleted_any:
        rprint("[yellow]⚠ No configuration found to delete[/yellow]")
    else:
        rprint("[dim]Note: PYXOS_* environment variables must be cleared manually (export -n PYXOS_...).[/dim]")


# ── diff ──────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("query", required=False)
@click.option("--output", "-o", "local_path_override", help="Override local path for comparison")
def diff(query, local_path_override):
    """Compare local project with remote version."""
    cfg = load_config()
    require_storage(cfg)
    db = get_db()

    if not query:
        project = _select_project(db)
        if not project:
            db.close()
            return
    else:
        project = _resolve_project(db, query)
        if not project:
            rprint(f"[red]✗ Project '{query}' not found.[/red]")
            db.close()
            return

    local_path = local_path_override or project.get("local_path")
    if not local_path or not Path(local_path).exists():
        local_display = local_path or "(none)"
        rprint(f"[yellow]Cannot compare — local path unavailable: {local_display}[/yellow]")
        db.close()
        return

    local_path = Path(local_path)
    project_name = project.get("name", "unnamed")

    rprint(f"[cyan]Comparing local '{local_path}' with remote '{project_name}'...[/cyan]")

    _, total_size = get_archive_file_list(local_path)
    local_files, _ = get_archive_file_list(local_path)
    local_file_map = {}
    for fpath, fsize in local_files:
        full = local_path / fpath
        local_file_map[fpath] = {"size": fsize, "mtime": full.stat().st_mtime if full.exists() else 0}

    remote_file_count = project.get("file_count", 0)
    remote_size = project.get("file_size", 0)

    added = []
    deleted = []
    modified = []

    public_id = project.get("storage_public_id") or project.get("cloudinary_public_id")
    remote_files = []

    if public_id:
        tmpdir = Path(tempfile.mkdtemp())
        try:
            archive_path = cloud_download(public_id, tmpdir)
            import zipfile
            with zipfile.ZipFile(str(archive_path), "r") as zf:
                for info in zf.infolist():
                    if not info.is_dir():
                        remote_files.append((info.filename, info.file_size, info.date_time))
        except Exception:
            remote_files = []
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    remote_file_map = {}
    for fname, fsize, date_time in remote_files:
        from datetime import datetime
        try:
            mtime = datetime(*date_time).timestamp()
        except Exception:
            mtime = 0
        remote_file_map[fname] = {"size": fsize, "mtime": mtime}

    all_paths = sorted(set(list(local_file_map.keys()) + list(remote_file_map.keys())))

    for fname in all_paths:
        in_local = fname in local_file_map
        in_remote = fname in remote_file_map
        if in_local and not in_remote:
            added.append(fname)
        elif not in_local and in_remote:
            deleted.append(fname)
        elif in_local and in_remote:
            local_sz = local_file_map[fname]["size"]
            remote_sz = remote_file_map[fname]["size"]
            local_mt = local_file_map[fname].get("mtime", 0)
            remote_mt = remote_file_map[fname].get("mtime", 0)
            if local_sz != remote_sz or abs(local_mt - remote_mt) > 1:
                modified.append(fname)

    console.print()
    table = Table(title=f"Diff: {project_name}", show_header=True, header_style="bold cyan")
    table.add_column("Status", style="bold")
    table.add_column("File")

    for f in added:
        table.add_row("[green]+ added[/green]", f)
    for f in deleted:
        table.add_row("[red]- deleted[/red]", f)
    for f in modified:
        table.add_row("[yellow]~ modified[/yellow]", f)

    if not added and not deleted and not modified:
        rprint("[green]No differences — local and remote are in sync.[/green]")
    else:
        console.print(table)
        rprint(f"\n[dim]Summary: {len(added)} added, {len(deleted)} deleted, {len(modified)} modified[/dim]")

    rfile_count = remote_file_count if remote_file_count is not None else len(remote_files)
    rfile_size = remote_size if remote_size is not None else sum(sz for _, sz, _ in remote_files)
    rprint(f"[dim]Remote: {rfile_count} files, {_format_size(rfile_size)}[/dim]")
    rprint(f"[dim]Local:  {len(local_files)} files, {_format_size(total_size)}[/dim]")
    db.close()


# ── export ────────────────────────────────────────────────────────────────────

@main.command()
@click.option("--output", "-o", "output_file", help="Output file path")
@click.option("--format", "-f", "fmt", type=click.Choice(["json", "csv"]), default="json", help="Export format")
@click.option("--query", "-q", help="Export a single project by name or ID")
def export(output_file, fmt, query):
    """Export project metadata to JSON or CSV file."""
    db = get_db()

    if query:
        project = _resolve_project(db, query)
        if not project:
            rprint(f"[red]✗ Project '{query}' not found.[/red]")
            db.close()
            return
        projects = [project]
    else:
        projects = _fetch_all_projects(db)

    if not projects:
        rprint("[yellow]No projects to export.[/yellow]")
        db.close()
        return

    if not output_file:
        from datetime import datetime as dt
        ts = dt.now().strftime("%Y%m%d-%H%M%S")
        output_file = f"pyxos-export-{ts}.{fmt}"
    else:
        output_file = str(Path(output_file))

    if fmt == "json":
        _export_json(projects, output_file)
    else:
        _export_csv(projects, output_file)

    rprint(f"[bold green]✓ Exported {len(projects)} project(s) to {output_file}[/bold green]")
    db.close()


def _export_json(projects, output_file):
    from bson import json_util
    data = json_util.dumps(projects, indent=2)
    Path(output_file).write_text(data, encoding="utf-8")


def _export_csv(projects, output_file):
    import csv
    fieldnames = ["_id", "name", "description", "tags", "version", "file_size", "file_count",
                  "storage_url", "storage_type", "encrypted", "created_at", "updated_at"]
    with _open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for p in projects:
            row = dict(p)
            row["_id"] = str(row.get("_id", ""))
            tags_val = row.get("tags", [])
            row["tags"] = ", ".join(tags_val) if tags_val else ""
            writer.writerow(row)


# ── import ────────────────────────────────────────────────────────────────────

@main.command("import")
@click.argument("file", type=click.Path(exists=True))
@click.option("--merge", is_flag=True, help="Overwrite existing projects by name")
def import_projects(file, merge):
    """Import project metadata from JSON or CSV file (metadata only, no storage upload)."""
    file_path = Path(file)
    suffix = file_path.suffix.lower()

    if suffix == ".json":
        from bson import json_util
        raw = file_path.read_text(encoding="utf-8")
        data = json_util.loads(raw)
        if isinstance(data, dict):
            data = [data]
    elif suffix == ".csv":
        import csv as _csv
        with _open(file_path, "r", encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            data = list(reader)
            for row in data:
                row["tags"] = [t.strip() for t in row.get("tags", "").split(",") if t.strip()]
                row["file_size"] = int(row.get("file_size", 0))
                row["file_count"] = int(row.get("file_count", 0))
                row["encrypted"] = row.get("encrypted", "").lower() in ("true", "1", "yes")
    else:
        rprint(f"[red]✗ Unsupported file format: {suffix}. Use .json or .csv[/red]")
        return

    cfg = load_config()
    db = get_db()

    imported = 0
    skipped = 0
    updated = 0

    for item in data:
        name = item.get("name")
        if not name:
            skipped += 1
            continue

        existing = db.get_project(name=name)
        if existing and not merge:
            skipped += 1
            continue

        if existing and merge:
            db.collection.update_one(
                {"name": name},
                {"$set": {
                    "description": item.get("description", ""),
                    "tags": item.get("tags", []) if isinstance(item.get("tags"), list) else [],
                    "version": item.get("version", "1.0.0"),
                    "file_size": item.get("file_size", 0),
                    "file_count": item.get("file_count", 0),
                    "storage_url": item.get("storage_url", ""),
                    "storage_public_id": item.get("storage_public_id", ""),
                    "storage_type": item.get("storage_type", cfg.get("storage_type", "cloudinary")),
                    "encrypted": item.get("encrypted", False),
                    "updated_at": datetime.now(timezone.utc),
                }}
            )
            updated += 1
        else:
            db.create_project(
                name=name,
                description=item.get("description", ""),
                tags=item.get("tags", []) if isinstance(item.get("tags"), list) else [],
                storage_url=item.get("storage_url", ""),
                storage_public_id=item.get("storage_public_id", ""),
                local_path=item.get("local_path", ""),
                file_size=item.get("file_size", 0),
                file_count=item.get("file_count", 0),
                version=item.get("version", "1.0.0"),
                storage_type=item.get("storage_type", cfg.get("storage_type", "cloudinary")),
                encrypted=item.get("encrypted", False),
            )
            imported += 1

    parts = []
    if imported:
        parts.append(f"{imported} imported")
    if updated:
        parts.append(f"{updated} updated")
    if skipped:
        parts.append(f"{skipped} skipped")
    rprint(f"[bold green]✓ Import complete: {', '.join(parts)}[/bold green]")
    db.close()


# ── stats ─────────────────────────────────────────────────────────────────────

@main.command()
def stats():
    """Show project statistics."""
    db = get_db()

    projects = _fetch_all_projects(db)

    if not projects:
        rprint("[yellow]No projects found.[/yellow]")
        db.close()
        return

    total = len(projects)
    total_size = sum(p.get("file_size", 0) for p in projects)
    avg_size = total_size / total if total > 0 else 0

    b2_count = sum(1 for p in projects if p.get("storage_type") == "b2")
    cloudinary_count = total - b2_count

    tag_counts = {}
    for p in projects:
        for t in p.get("tags", []):
            tag_counts[t] = tag_counts.get(t, 0) + 1
    top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    latest = max(projects, key=lambda p: p.get("updated_at") or datetime.min.replace(tzinfo=timezone.utc))
    largest = max(projects, key=lambda p: p.get("file_size", 0))

    month_counts = {}
    for p in projects:
        ca = p.get("created_at")
        if ca:
            key = ca.strftime("%Y-%m")
            month_counts[key] = month_counts.get(key, 0) + 1
    sorted_months = sorted(month_counts.items())

    content = f"[bold cyan]Total Projects:[/bold cyan]      {total}\n"
    content += f"[bold cyan]Total Size:[/bold cyan]         {_format_size(total_size)}\n"
    content += f"[bold cyan]Average Size:[/bold cyan]      {_format_size(int(avg_size))}\n\n"

    content += "[bold cyan]Storage Backend:[/bold cyan]\n"
    content += f"  Cloudinary:  {cloudinary_count}\n"
    content += f"  B2:          {b2_count}\n\n"

    if top_tags:
        content += "[bold cyan]Top Tags:[/bold cyan]\n"
        for tag, count in top_tags:
            content += f"  [green]{tag}[/green]: {count}\n"
        content += "\n"

    latest_name = latest.get("name", "-")
    latest_updated = latest.get("updated_at")
    latest_str = latest_updated.strftime("%Y-%m-%d %H:%M UTC") if latest_updated else "-"
    content += f"[bold cyan]Latest Project:[/bold cyan]     {latest_name} ([dim]{latest_str}[/dim])\n"

    largest_name = largest.get("name", "-")
    content += f"[bold cyan]Largest Project:[/bold cyan]    {largest_name} ({_format_size(largest.get('file_size', 0))})\n\n"

    if sorted_months:
        content += "[bold cyan]Projects by Month:[/bold cyan]\n"
        for month, count in sorted_months:
            content += f"  {month}: {count}\n"

    console.print(Panel.fit(content, title="Pyxos Statistics", border_style="cyan"))
    db.close()


# ── helpers ───────────────────────────────────────────────────────────────────

def _fetch_all_projects(db):
    all_projects, total = db.list_projects(per_page=1000)
    if total > 1000:
        page = 2
        while len(all_projects) < total:
            more, _ = db.list_projects(per_page=1000, page=page)
            if not more:
                break
            all_projects.extend(more)
            page += 1
    return all_projects


def _print_info_panel(project):
    created = project.get("created_at")
    updated = project.get("updated_at")
    fmt = "%Y-%m-%d %H:%M UTC"

    if isinstance(created, str):
        created_str = created
    elif created:
        created_str = created.strftime(fmt)
    else:
        created_str = "-"

    if isinstance(updated, str):
        updated_str = updated
    elif updated:
        updated_str = updated.strftime(fmt)
    else:
        updated_str = "-"

    panel_content = f"[bold cyan]{project['name']}[/bold cyan]\n"
    panel_content += f"  [dim]ID:[/dim]          {project.get('_id', '-')}\n"
    panel_content += f"  [dim]Version:[/dim]     {project.get('version', '-')}\n"

    description = project.get("description", "-") or "-"
    panel_content += "  [dim]Description:[/dim] see below\n"

    tags = project.get("tags", [])
    panel_content += f"  [dim]Tags:[/dim]        {', '.join(tags) if tags else '-'}\n"
    panel_content += f"  [dim]Files:[/dim]       {project.get('file_count', '-')}\n"
    panel_content += f"  [dim]Size:[/dim]        {_format_size(project.get('file_size', 0))}\n"
    panel_content += f"  [dim]Local Path:[/dim]  {project.get('local_path', '-') or '-'}\n"
    panel_content += f"  [dim]Storage URL:[/dim] {project.get('storage_url') or project.get('cloudinary_url') or '-'}\n"
    panel_content += f"  [dim]Encrypted:[/dim]   {'Yes' if project.get('encrypted') else 'No'}\n"
    panel_content += f"  [dim]Created:[/dim]     {created_str}\n"
    panel_content += f"  [dim]Updated:[/dim]     {updated_str}"

    console.print(Panel.fit(panel_content, title="Project Details", border_style="cyan"))

    if description and description != "-":
        console.print()
        md = Markdown(description)
        console.print(Panel(md, title="Description", border_style="cyan"))
        console.print(f"[dim]Raw: {description}[/dim]")


def _select_project_from_list(projects):
    if not projects:
        rprint("[yellow]No projects in cache.[/yellow]")
        return None

    table = Table(title="Select a project (cached)")
    table.add_column("#", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Version", style="magenta")
    table.add_column("Description")
    table.add_column("Updated", style="yellow")

    for i, p in enumerate(projects, 1):
        desc = (p.get("description") or "-")[:50]
        version = p.get("version", "-")
        updated = p.get("updated_at", "-")
        if isinstance(updated, str):
            updated_str = updated[:16] if updated else "-"
        elif updated:
            updated_str = updated.strftime("%Y-%m-%d %H:%M")
        else:
            updated_str = "-"
        table.add_row(str(i), p["name"], version, desc, updated_str)

    console.print(table)

    try:
        choice = click.prompt("\nEnter number", type=int)
        if 1 <= choice <= len(projects):
            return projects[choice - 1]
        rprint("[red]Invalid choice.[/red]")
    except (click.Abort, ValueError):
        pass
    return None


def _resolve_project_from_list(projects, query):
    for p in projects:
        if str(p.get("_id")) == query:
            return p
        if p.get("name") == query:
            return p
    return None


def _select_project(db):
    projects, _ = db.list_projects(per_page=50)
    if not projects:
        rprint("[yellow]No projects found.[/yellow]")
        return None

    table = Table(title="Select a project")
    table.add_column("#", style="cyan")
    table.add_column("Name", style="green")
    table.add_column("Version", style="magenta")
    table.add_column("Description")
    table.add_column("Updated", style="yellow")

    for i, p in enumerate(projects, 1):
        desc = (p.get("description") or "-")[:50]
        version = p.get("version", "-")
        updated = p.get("updated_at")
        updated_str = updated.strftime("%Y-%m-%d %H:%M") if updated else "-"
        table.add_row(str(i), p["name"], version, desc, updated_str)

    console.print(table)

    try:
        choice = click.prompt("\nEnter number", type=int)
        if 1 <= choice <= len(projects):
            return projects[choice - 1]
        rprint("[red]Invalid choice.[/red]")
    except (click.Abort, ValueError):
        pass
    return None


# ── web ────────────────────────────────────────────────────────────────────────

@main.command()
@click.option("--host", default="127.0.0.1", help="Host to bind")
@click.option("--port", default=8765, help="Port to bind")
def web(host, port):
    """Launch the Pyxos web dashboard."""
    try:
        from .web.app import create_app
    except ImportError:
        rprint("[red]✗ Optional dependency 'fenrir-framework' is not installed.[/red]")
        rprint("[yellow]Install it with:[/yellow]", end=" ")
        click.echo('pip install "pyxos[web]"')
        raise SystemExit(1)

    app = create_app()
    rprint(f"[cyan]Pyxos Dashboard running at http://{host}:{port}[/cyan]")
    app.run(host=host, port=port, app_path="pyxos.web.app:app")


@main.command("gui")
def gui_app():
    """Launch the desktop GUI application."""
    try:
        from pyxos.gui.main import gui_launch
        _ = gui_launch  # referenced via subprocess
    except ImportError:
        rprint("[red]✗ Optional dependency 'PySide6' is not installed.[/red]")
        rprint("[yellow]Install it with:[/yellow]", end=" ")
        click.echo('pip install "pyxos[gui]"')
        raise SystemExit(1)

    # Launch GUI directly after flushing Rich output
    import signal as _sig

    sys.stdout.flush()
    sys.stderr.flush()

    _sig.signal(_sig.SIGABRT, lambda *_: sys.exit(0))
    gui_launch()


# ── completion ───────────────────────────────────────────────────────────────

@main.group()
def completion():
    """Shell completion commands."""


@completion.command()
def bash():
    """Generate bash completion script."""
    click.echo('eval "$(_PYXOS_COMPLETE=bash_source pyxos)"')


@completion.command()
def zsh():
    """Generate zsh completion script."""
    click.echo('eval "$(_PYXOS_COMPLETE=zsh_source pyxos)"')


@completion.command()
def fish():
    """Generate fish completion script."""
    click.echo('pyxos completion fish | source')
    click.echo('')
    click.echo('# Or for a permanent fish completion script:')
    click.echo('# echo "eval (env _PYXOS_COMPLETE=fish_source pyxos | source)" >> ~/.config/fish/completions/pyxos.fish')


@completion.command()
def install():
    """Auto-detect shell and install completion."""
    shell = os.environ.get("SHELL", "").lower()
    if "zsh" in shell:
        shell_type = "zsh"
    elif "fish" in shell:
        shell_type = "fish"
    elif "bash" in shell:
        shell_type = "bash"
    else:
        rprint("[red]✗ Could not detect shell. Run: pyxos completion [bash|zsh|fish][/red]")
        return

    rprint(f"[cyan]Detected shell: {shell_type}[/cyan]")

    if shell_type == "bash":
        rc_path = Path.home() / ".bashrc"
        line = 'eval "$(_PYXOS_COMPLETE=bash_source pyxos)"'
    elif shell_type == "zsh":
        rc_path = Path.home() / ".zshrc"
        line = 'eval "$(_PYXOS_COMPLETE=zsh_source pyxos)"'
    elif shell_type == "fish":
        rc_path = Path.home() / ".config" / "fish" / "config.fish"
        line = "pyxos completion fish | source"
    else:
        rc_path = None
        line = None

    if not rc_path or not line:
        return

    rc_path.parent.mkdir(parents=True, exist_ok=True)
    if rc_path.exists():
        content = rc_path.read_text()
        if line in content:
            rprint(f"[yellow]⚠ Completion already installed in {rc_path}[/yellow]")
            return

    with _open(rc_path, "a") as f:
        f.write(f"\n# Pyxos shell completion\n{line}\n")
    rprint(f"[green]✓ Added completion to {rc_path}[/green]")
    rprint(f"[dim]Restart your shell or run: source {rc_path}[/dim]")


# ── watch ─────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("path", type=click.Path(exists=True), default=".")
@click.option("--interval", "-i", type=float, default=2.0, help="Debounce interval in seconds (default: 2)")
@click.option("--name", "-n", help="Project name (defaults to directory name)")
def watch(path, interval, name):
    """Watch a directory for changes and auto-push to storage.

    Monitors a directory for file changes and automatically pushes
    to MongoDB Atlas & Cloudinary/B2 when changes are detected.
    Uses debouncing to batch changes together.
    """
    path = Path(path).resolve()
    project_name = name or get_project_name(path)

    cfg = load_config()
    require_storage(cfg)

    last_push_time = None
    files_changed = 0
    push_count = 0

    use_watchfiles = False
    try:
        from watchfiles import watch as wf_watch
        use_watchfiles = True
    except ImportError:
        rprint("[yellow]⚠ watchfiles not installed. Using polling fallback (pip install 'pyxos[watch]' for better performance).[/yellow]")

    rprint(f"[cyan]Watching '{path}' as project '{project_name}'...[/cyan]")
    rprint(f"[dim]Debounce interval: {interval}s. Press Ctrl+C to stop.[/dim]")
    rprint()

    def _get_state_snapshot():
        state = {}
        for entry in path.rglob("*"):
            if entry.is_file() and not entry.is_symlink():
                try:
                    state[str(entry.relative_to(path))] = entry.stat().st_size
                except OSError:
                    pass
        return state

    def _do_push():
        nonlocal last_push_time, files_changed, push_count
        try:
            db = Database(cfg["mongodb_uri"])
            existing = db.get_project(name=project_name)

            tmpdir = Path(tempfile.mkdtemp())
            archive_path = tmpdir / f"{project_name}.zip"
            try:
                file_count, _ = count_archive_files(path)
                make_archive(path, archive_path)
                actual_size = archive_path.stat().st_size

                storage_url, storage_public_id = cloud_upload(archive_path, project_name)

                if existing:
                    db.save_version(existing)
                    try:
                        cloud_delete(existing.get("storage_public_id") or existing.get("cloudinary_public_id"))
                    except RuntimeError:
                        pass
                    db.update_project(
                        existing["_id"],
                        storage_url=storage_url,
                        storage_public_id=storage_public_id,
                        file_size=actual_size,
                        file_count=file_count,
                    )
                else:
                    db.create_project(
                        name=project_name,
                        description="",
                        tags=[],
                        storage_url=storage_url,
                        storage_public_id=storage_public_id,
                        local_path=str(path),
                        file_size=actual_size,
                        file_count=file_count,
                        version="1.0.0",
                        storage_type=cfg.get("storage_type", "cloudinary"),
                    )
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
                db.close()

            last_push_time = datetime.now(timezone.utc)
            push_count += 1
            return True, actual_size, file_count
        except Exception as e:
            rprint(f"[red]Push failed: {e}[/red]")
            return False, 0, 0

    def _render_live(last_push, fchanged, pcount):
        datetime.now(timezone.utc)
        last_push_str = last_push.strftime("%Y-%m-%d %H:%M:%S UTC") if last_push else "Never"
        lines = [
            f"[bold cyan]Watching: {project_name}[/bold cyan]",
            f"  [dim]Path:[/dim]      {path}",
            f"  [dim]Status:[/dim]    {'Waiting for changes...' if not last_push else 'Monitoring...'}",
            f"  [dim]Last push:[/dim] {last_push_str}",
            f"  [dim]Push count:[/dim]{pcount}",
            f"  [dim]Files changed:[/dim] {fchanged}",
        ]
        return "\n".join(lines)

    if use_watchfiles:
        debounce_timer = None
        last_render_str = _render_live(None, 0, 0)

        with Live(last_render_str, console=console, refresh_per_second=4) as live:
            try:
                for changes in wf_watch(path):
                    changed_count = len(changes)
                    now = time.time()
                    if debounce_timer and now - debounce_timer >= interval:
                        live.update("[cyan]Pushing changes...[/cyan]", refresh=True)
                        success, size, fcount = _do_push()
                        if success:
                            last_push_time = time.time()
                            push_count += 1
                            files_changed = 0
                            live.update(f"[green]✓ Pushed ({_format_size(size)}, {fcount} files)[/green]", refresh=True)
                        else:
                            live.update("[red]✗ Push failed[/red]", refresh=True)
                        debounce_timer = None
                    files_changed += changed_count
                    live.update(_render_live(last_push_time, files_changed, push_count), refresh=True)
                    debounce_timer = time.time()
            except KeyboardInterrupt:
                pass

            if debounce_timer and time.time() - debounce_timer < interval:
                remaining = interval - (time.time() - debounce_timer)
                live.update(f"[yellow]Debouncing... waiting {remaining:.1f}s[/yellow]", refresh=True)
                time.sleep(remaining)

            if debounce_timer and files_changed > 0:
                live.update("[cyan]Pushing changes...[/cyan]", refresh=True)
                success, size, fcount = _do_push()
                if success:
                    live.update(f"[green]✓ Pushed ({_format_size(size)}, {fcount} files)[/green]", refresh=True)
                else:
                    live.update("[red]✗ Push failed[/red]", refresh=True)
                time.sleep(1)
    else:
        prev_state = _get_state_snapshot()
        last_render_str = _render_live(None, 0, 0)

        with Live(last_render_str, console=console, refresh_per_second=4) as live:
            changes_pending = False
            try:
                while True:
                    current_state = _get_state_snapshot()
                    if current_state != prev_state:
                        changed = set(current_state.keys()) - set(prev_state.keys())
                        removed = set(prev_state.keys()) - set(current_state.keys())
                        modified_keys = set()
                        for k in set(current_state.keys()) & set(prev_state.keys()):
                            if current_state[k] != prev_state[k]:
                                modified_keys.add(k)
                        total_changed = len(changed) + len(removed) + len(modified_keys)
                        files_changed += total_changed
                        prev_state = current_state
                        changes_pending = True
                        debounce_timer = time.time()
                        rprint(f"[yellow]Change detected: {total_changed} files[/yellow]")
                        live.update(_render_live(last_push_time, files_changed, push_count), refresh=True)
                    elif changes_pending and debounce_timer and time.time() - debounce_timer >= interval:
                        changes_pending = False
                        live.update("[cyan]Pushing changes...[/cyan]", refresh=True)
                        success, size, fcount = _do_push()
                        if success:
                            live.update(f"[green]✓ Pushed ({_format_size(size)}, {fcount} files)[/green]", refresh=True)
                            live.update(_render_live(last_push_time, files_changed, push_count), refresh=True)
                        else:
                            live.update("[red]✗ Push failed[/red]", refresh=True)
                    else:
                        live.update(_render_live(last_push_time, files_changed, push_count), refresh=True)
                    time.sleep(max(0.5, interval / 4))
            except KeyboardInterrupt:
                pass

    console.print()
    rprint("[bold yellow]Watch stopped.[/bold yellow]")
    rprint(f"  Total pushes:    {push_count}")
    rprint(f"  Files changed:   {files_changed}")
    if last_push_time:
        rprint(f"  Last push:       {last_push_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    rprint(f"  Project:         {project_name}")
    rprint(f"  Path:            {path}")
