import os
import shutil
import sys
import tempfile
import webbrowser
from pathlib import Path

import click
import cloudinary.exceptions
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint
from bson.errors import InvalidId

from .config import (
    load_config,
    save_config,
    delete_config,
    get_config_source,
    get_project_name,
    make_archive,
    count_archive_files,
    get_archive_file_list,
    build_exclude_patterns,
)
from .database import Database
from .storage import (
    upload_project as cloud_upload,
    delete_project as cloud_delete,
    download_project as cloud_download,
    init_storage,
    ping_storage,
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
    if not size:
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
def main():
    """Pyxos - Project Management CLI.

    Push/pull projects to/from MongoDB Atlas and Cloudinary/B2.
    """
    rprint(LOGO)

# ── init ──────────────────────────────────────────────────────────────────────

@main.command()
@click.option("--storage-type", prompt="Storage backend (cloudinary/b2)", type=click.Choice(["cloudinary", "b2"]))
@click.option("--mongodb-uri", prompt="MongoDB Atlas URI", hide_input=True)
@click.option("--cloudinary-cloud-name", default="")
@click.option("--cloudinary-api-key", default="")
@click.option("--cloudinary-api-secret", default="")
@click.option("--b2-application-key-id", default="")
@click.option("--b2-application-key", default="")
@click.option("--b2-bucket-name", default="")
def init(storage_type, mongodb_uri, cloudinary_cloud_name, cloudinary_api_key, cloudinary_api_secret,
         b2_application_key_id, b2_application_key, b2_bucket_name):
    """Initialize Pyxos configuration."""
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
def push(path, name, description, tags, version, force, dry_run, no_confirm_size, extra_excludes, extra_includes):
    """Push a local project to MongoDB Atlas & Cloudinary."""
    path = Path(path).resolve()
    project_name = name or get_project_name(path)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    excl = list(extra_excludes) if extra_excludes else None
    incl = list(extra_includes) if extra_includes else None

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
        rprint(f"\n[yellow]Dry run — nothing uploaded.[/yellow]")
        return

    if total_size > SIZE_WARNING_THRESHOLD and not no_confirm_size:
        threshold_mb = SIZE_WARNING_THRESHOLD / (1024 * 1024)
        if click.confirm(f"[yellow]Project is {total_size_mb:.1f} MB (threshold: {threshold_mb:.0f} MB). Continue?[/yellow]", default=False) is not True:
            rprint("[yellow]Cancelled.[/yellow]")
            return

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
        make_archive(path, archive_path, excl, incl)
        actual_size = archive_path.stat().st_size
        rprint(f"[green]✓ Archive created ({_format_size(actual_size)})[/green]")

        try:
            storage_url, storage_public_id = cloud_upload(archive_path, project_name)
        except ValueError as e:
            rprint(f"[yellow]⚠ {e}[/yellow]")
            return
        except (cloudinary.exceptions.Error, RuntimeError) as e:
            rprint(f"[red]✗ Storage error: {e}[/red]")
            return

        rprint(f"[green]✓ Uploaded to storage[/green]")

        if existing and force:
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
        )

        rprint(f"\n[bold green]✓ Project '{project_name}' pushed successfully![/bold green]")
        rprint(f"  ID:        {project_id}")
        rprint(f"  Version:   {version}")
        rprint(f"  Files:     {file_count}")
        rprint(f"  Size:      {_format_size(actual_size)}")
        rprint(f"  URL:       {storage_url}")

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    db.close()


# ── pull ──────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("query", required=False)
@click.option("--output", "-o", default=".", help="Output directory")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing directory")
def pull(query, output, force):
    """Pull a project from MongoDB Atlas & Cloudinary to local."""
    cfg = load_config()
    require_storage(cfg)
    db = get_db()

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
        rprint(f"[cyan]Extracting to {out_dir}...[/cyan]")
        shutil.unpack_archive(str(archive_path), str(out_dir))
        rprint(f"[bold green]✓ Project '{project_name}' pulled to {out_dir}[/bold green]")
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

        local_path = Path(local_path)
        refresh_name = name or project["name"]
        file_count, _ = count_archive_files(local_path)

        tmpdir = Path(tempfile.mkdtemp())
        archive_path = tmpdir / f"{refresh_name}.zip"
        try:
            rprint(f"[cyan]Re-packaging from {local_path}...[/cyan]")
            make_archive(local_path, archive_path)
            actual_size = archive_path.stat().st_size

            rprint(f"[cyan]Re-uploading to storage...[/cyan]")
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


# ── info ──────────────────────────────────────────────────────────────────────

@main.command()
@click.argument("query", required=False)
def info(query):
    """Show detailed information about a project."""
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

    created = project.get("created_at")
    updated = project.get("updated_at")
    fmt = "%Y-%m-%d %H:%M UTC"

    panel_content = f"[bold cyan]{project['name']}[/bold cyan]\n"
    panel_content += f"  [dim]ID:[/dim]          {project['_id']}\n"
    panel_content += f"  [dim]Version:[/dim]     {project.get('version', '-')}\n"
    panel_content += f"  [dim]Description:[/dim] {project.get('description', '-') or '-'}\n"
    tags = project.get("tags", [])
    panel_content += f"  [dim]Tags:[/dim]        {', '.join(tags) if tags else '-'}\n"
    panel_content += f"  [dim]Files:[/dim]       {project.get('file_count', '-')}\n"
    panel_content += f"  [dim]Size:[/dim]        {_format_size(project.get('file_size', 0))}\n"
    panel_content += f"  [dim]Local Path:[/dim]  {project.get('local_path', '-') or '-'}\n"
    panel_content += f"  [dim]Storage URL:[/dim] {project.get('storage_url') or project.get('cloudinary_url') or '-'}\n"
    panel_content += f"  [dim]Created:[/dim]     {created.strftime(fmt) if created else '-'}\n"
    panel_content += f"  [dim]Updated:[/dim]     {updated.strftime(fmt) if updated else '-'}"

    console.print(Panel.fit(panel_content, title="Project Details", border_style="cyan"))
    db.close()


# ── list ──────────────────────────────────────────────────────────────────────

@main.command("list")
@click.option("--search", "-s", help="Search by name or description")
@click.option("--tag", "-t", multiple=True, help="Filter by tag (repeatable)")
@click.option("--page", "-p", type=int, default=1, help="Page number")
@click.option("--per-page", type=int, default=20, help="Results per page")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
def list_projects(search, tag, page, per_page, json_output):
    """List all projects in MongoDB Atlas."""
    db = get_db()
    tags = list(tag) if tag else None

    with console.status("[cyan]Querying database...[/cyan]"):
        projects, total = db.list_projects(search=search, tags=tags, page=page, per_page=per_page)

    if not projects:
        rprint("[yellow]No projects found.[/yellow]")
        db.close()
        return

    if json_output:
        from bson import json_util
        click.echo(json_util.dumps({"total": total, "page": page, "projects": projects}, indent=2))
        db.close()
        return

    total_pages = max(1, (total + per_page - 1) // per_page)

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
        updated_str = updated.strftime("%Y-%m-%d %H:%M") if updated else "-"

        table.add_row(p["name"], version, desc, tags_str, _format_size(p.get("file_size", 0)), updated_str)

    console.print(table)

    if page < total_pages:
        rprint(f"[dim]Next page: pyxos list --page {page + 1}[/dim]")

    db.close()


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
            rprint(f"[green]✓ Deleted from storage[/green]")
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
    table.add_row("config_file", str((Path.home() / ".pyxos" / "config.json")))

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


# ── helpers ───────────────────────────────────────────────────────────────────

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
