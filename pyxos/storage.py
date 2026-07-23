import urllib.request
import urllib.error
from pathlib import Path

import cloudinary.uploader
import cloudinary.api
from cloudinary import config as cloudinary_config
from cloudinary.utils import cloudinary_url
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, DownloadColumn, TransferSpeedColumn

console = Console()

CLOUDINARY_MAX_SIZE = 10 * 1024 * 1024

_state = {}
_b2_bucket = None


def init_storage(config):
    global _state, _b2_bucket
    _state = config
    storage_type = config.get("storage_type", "cloudinary")

    if storage_type == "cloudinary":
        required = ["cloudinary_cloud_name", "cloudinary_api_key", "cloudinary_api_secret"]
        missing = [k for k in required if not config.get(k)]
        if missing:
            raise ValueError(f"Missing Cloudinary config: {', '.join(missing)}")
        cloudinary_config(
            cloud_name=config["cloudinary_cloud_name"],
            api_key=config["cloudinary_api_key"],
            api_secret=config["cloudinary_api_secret"],
            secure=True,
        )
    elif storage_type == "b2":
        from b2sdk.v2 import InMemoryAccountInfo, B2Api
        required = ["b2_application_key_id", "b2_application_key", "b2_bucket_name"]
        missing = [k for k in required if not config.get(k)]
        if missing:
            raise ValueError(f"Missing B2 config: {', '.join(missing)}")
        info = InMemoryAccountInfo()
        b2_api = B2Api(info)
        b2_api.authorize_account("production", config["b2_application_key_id"], config["b2_application_key"])
        _b2_bucket = b2_api.get_bucket_by_name(config["b2_bucket_name"])
    else:
        raise ValueError(f"Unknown storage type: {storage_type}")


def _storage_type():
    return _state.get("storage_type", "cloudinary")


# ── Upload ─────────────────────────────────────────────────────────────────

def upload_project(archive_path, project_name):
    if _storage_type() == "b2":
        return _b2_upload(archive_path, project_name)
    return _cloudinary_upload(archive_path, project_name)


def _cloudinary_upload(archive_path, project_name):
    file_size = Path(archive_path).stat().st_size

    if file_size > CLOUDINARY_MAX_SIZE:
        raise ValueError(
            f"Archive size ({_fmt(file_size)}) exceeds Cloudinary free tier limit ({_fmt(CLOUDINARY_MAX_SIZE)}). "
            "Upgrade Cloudinary plan or switch to B2 (pyxos init)."
        )

    with console.status("[cyan]Uploading to Cloudinary...[/cyan]"):
        result = cloudinary.uploader.upload(
            str(archive_path),
            resource_type="raw",
            public_id=f"pyxos/{project_name}",
            use_filename=True,
            unique_filename=False,
            overwrite=True,
        )

    public_id = result["public_id"]
    url, _ = cloudinary_url(public_id, resource_type="raw")
    return url, public_id


def _b2_upload(archive_path, project_name):
    from b2sdk.v2 import UploadSourceLocalFile

    b2_file_name = f"pyxos/{project_name}.zip"

    with console.status("[cyan]Uploading to Backblaze B2...[/cyan]"):
        _b2_bucket.upload(UploadSourceLocalFile(str(archive_path)), b2_file_name)

    url = _b2_bucket.get_download_url(b2_file_name)
    return url, b2_file_name


# ── Delete ─────────────────────────────────────────────────────────────────

def delete_project(public_id):
    if _storage_type() == "b2":
        return _b2_delete(public_id)
    return _cloudinary_delete(public_id)


def _cloudinary_delete(public_id):
    try:
        cloudinary.uploader.destroy(public_id, resource_type="raw")
        return True
    except cloudinary.exceptions.Error as e:
        raise RuntimeError(f"Cloudinary error: {e}") from e


def _b2_delete(public_id):
    from b2sdk.v2.exception import B2Error
    try:
        for file_version in _b2_bucket.list_file_versions(public_id):
            _b2_bucket.delete_file_version(file_version.id_, file_version.file_name)
        return True
    except B2Error as e:
        raise RuntimeError(f"B2 error: {e}") from e


# ── Download ───────────────────────────────────────────────────────────────

def download_project(public_id, dest_dir):
    if _storage_type() == "b2":
        return _b2_download(public_id, dest_dir)
    return _cloudinary_download(public_id, dest_dir)


def _cloudinary_download(public_id, dest_dir):
    url, _ = cloudinary_url(public_id, resource_type="raw")
    return _download_url(url, public_id, dest_dir)


def _b2_download(public_id, dest_dir):
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    archive_filename = public_id.replace("/", "_")
    if not archive_filename.endswith(".zip"):
        archive_filename += ".zip"
    archive_path = dest_dir / archive_filename

    with console.status("[cyan]Downloading from Backblaze B2...[/cyan]"):
        downloaded = _b2_bucket.download_file_by_name(public_id)
        downloaded.save_to(archive_path)

    return archive_path


def _download_url(url, public_id, dest_dir):
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    archive_filename = public_id.replace("/", "_") + ".zip"
    archive_path = dest_dir / archive_filename

    with Progress(
        TextColumn("[cyan]Downloading...[/cyan]"),
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
        "•",
        DownloadColumn(),
        "•",
        TransferSpeedColumn(),
    ) as progress:
        task = progress.add_task("download", total=None)

        try:
            response = urllib.request.urlopen(url, timeout=300)
            content_length = response.headers.get("Content-Length")
            if content_length:
                progress.update(task, total=int(content_length))

            chunk_size = 1024 * 64
            downloaded = 0
            with open(archive_path, "wb") as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    progress.update(task, completed=downloaded)

        except (IOError, urllib.error.URLError, ValueError) as e:
            if archive_path.exists():
                archive_path.unlink()
            raise RuntimeError(f"Download failed: {e}") from e

    return archive_path


# ── Ping ───────────────────────────────────────────────────────────────────

def ping_storage():
    if _storage_type() == "b2":
        return _b2_ping()
    return _cloudinary_ping()


def _cloudinary_ping():
    try:
        cloudinary.api.ping()
        return True
    except cloudinary.exceptions.Error:
        return False


def _b2_ping():
    from b2sdk.v2.exception import B2Error
    try:
        next(_b2_bucket.ls("pyxos/", fetch_count=1), None)
        return True
    except B2Error:
        return False


# ── Helpers ────────────────────────────────────────────────────────────────

def _fmt(size):
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / 1024:.1f} KB"


def ping_cloudinary():
    return _cloudinary_ping()
