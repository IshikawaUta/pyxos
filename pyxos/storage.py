import os
import urllib.error
import urllib.request
from pathlib import Path

import cloudinary.api
import cloudinary.uploader
from cloudinary import config as cloudinary_config
from cloudinary.utils import cloudinary_url
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TransferSpeedColumn,
)

console = Console()

CLOUDINARY_MAX_SIZE = 10 * 1024 * 1024
B2_LARGE_FILE_THRESHOLD = 200 * 1024 * 1024
B2_CHUNK_SIZE = 100 * 1024 * 1024

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
        from b2sdk.v2 import B2Api, InMemoryAccountInfo
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

    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]Uploading to Cloudinary...[/cyan]"),
        BarColumn(),
    ) as progress:
        task = progress.add_task("upload", total=None)
        result = cloudinary.uploader.upload(
            str(archive_path),
            resource_type="raw",
            public_id=f"pyxos/{project_name}",
            use_filename=True,
            unique_filename=False,
            overwrite=True,
        )
        progress.update(task, completed=1, total=1)

    public_id = result["public_id"]
    url, _ = cloudinary_url(public_id, resource_type="raw")
    return url, public_id


def _b2_upload(archive_path, project_name):
    from b2sdk.v2 import UploadSourceLocalFile

    b2_file_name = f"pyxos/{project_name}.zip"
    file_size = Path(archive_path).stat().st_size

    if file_size > B2_LARGE_FILE_THRESHOLD:
        return _b2_upload_large(archive_path, b2_file_name, file_size)

    from b2sdk.v2 import AbstractProgressListener

    class UploadProgressListener(AbstractProgressListener):
        def __init__(self, progress, task):
            self.progress = progress
            self.task = task

        def set_total_bytes(self, total_byte_count):
            self.progress.update(self.task, total=total_byte_count)

        def bytes_completed(self, byte_count):
            self.progress.update(self.task, completed=byte_count)

        def close(self):
            pass

    with Progress(
        TextColumn("[cyan]Uploading to Backblaze B2...[/cyan]"),
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
        "•",
        TransferSpeedColumn(),
    ) as progress:
        task = progress.add_task("upload", total=file_size)
        listener = UploadProgressListener(progress, task)
        _b2_bucket.upload(
            UploadSourceLocalFile(str(archive_path)),
            b2_file_name,
            progress_listener=listener,
        )

    url = _b2_bucket.get_download_url(b2_file_name)
    return url, b2_file_name


def _b2_upload_large(archive_path, b2_file_name, file_size):
    from b2sdk.v2 import UploadSourceLocalFileRange

    total_parts = (file_size + B2_CHUNK_SIZE - 1) // B2_CHUNK_SIZE

    large_file = _b2_bucket.start_large_file(b2_file_name, content_type="application/zip")
    part_sha1s = []
    completed = 0

    try:
        with Progress(
            TextColumn("[cyan]Uploading large file to Backblaze B2...[/cyan]"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            "•",
            TransferSpeedColumn(),
            TextColumn("[dim]{task.fields[part_info]}[/dim]"),
        ) as progress:
            task = progress.add_task("upload", total=file_size, part_info="")

            for part_number in range(1, total_parts + 1):
                offset = (part_number - 1) * B2_CHUNK_SIZE
                length = min(B2_CHUNK_SIZE, file_size - offset)

                progress.update(task, part_info=f"Part {part_number}/{total_parts}")

                result = _b2_bucket.upload_part(
                    large_file.file_id,
                    part_number,
                    UploadSourceLocalFileRange(str(archive_path), offset=offset, length=length),
                )

                part_sha1s.append(result.content_sha1)
                completed += length
                progress.update(task, completed=completed)

        _b2_bucket.finish_large_file(large_file.file_id, part_sha1s)
    except Exception:
        _b2_bucket.cancel_large_file(large_file.file_id)
        raise

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
    auth_token = _b2_bucket.get_download_authorization(public_id, 600)
    base_url = _b2_bucket.get_download_url(public_id)
    url = f"{base_url}?Authorization={auth_token}"
    return _download_url(url, public_id, dest_dir, resume=True)


def _download_url(url, public_id, dest_dir, resume=True):
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    archive_filename = public_id.replace("/", "_")
    if not archive_filename.endswith(".zip"):
        archive_filename += ".zip"
    archive_path = dest_dir / archive_filename
    part_path = dest_dir / (archive_filename + ".part")

    mode = "ab" if resume and part_path.exists() else "wb"
    try:
        downloaded = part_path.stat().st_size if resume and part_path.exists() else 0
    except OSError:
        downloaded = 0
        mode = "wb"

    opener = urllib.request.build_opener()
    if downloaded > 0 and resume:
        opener.addheaders = [("Range", f"bytes={downloaded}-")]

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
        if downloaded > 0:
            progress.update(task, completed=downloaded)

        try:
            response = opener.open(url, timeout=300)
            status = response.status
            if status >= 400:
                response.close()
                raise RuntimeError(f"Download failed: HTTP {status}")
            if downloaded > 0 and status == 206:
                content_range = response.headers.get("Content-Range", "")
                if "bytes" in content_range:
                    total_from_range = int(content_range.split("/")[-1])
                    progress.update(task, total=total_from_range)
            elif downloaded > 0 and status == 200:
                downloaded = 0
                mode = "wb"
                os.remove(part_path)

            content_length = response.headers.get("Content-Length")
            if content_length:
                cl = int(content_length)
                if status == 200:
                    progress.update(task, total=cl)
                elif status == 206:
                    progress.update(task, total=downloaded + cl)

            chunk_size = 1024 * 64
            with open(part_path, mode) as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    progress.update(task, completed=downloaded)

        except (OSError, urllib.error.URLError, ValueError) as e:
            if part_path.exists() and mode == "wb":
                part_path.unlink()
            raise RuntimeError(f"Download failed: {e}") from e

    part_path.rename(archive_path)
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


def generate_share_link(public_id, expiration_seconds=3600):
    if _storage_type() == "b2":
        return _b2_share_link(public_id, expiration_seconds)
    return _cloudinary_share_link(public_id, expiration_seconds)


def _cloudinary_share_link(public_id, expiration_seconds):
    from datetime import datetime, timedelta, timezone
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expiration_seconds)
    url, _ = cloudinary_url(
        public_id,
        resource_type="raw",
        sign_url=True,
        expires_at=expires_at,
    )
    return url, expires_at


def _b2_share_link(public_id, expiration_seconds):
    from datetime import datetime, timedelta, timezone
    auth = _b2_bucket.get_download_authorization(
        public_id,
        valid_duration_in_seconds=expiration_seconds,
    )
    url = _b2_bucket.get_download_url(public_id)
    signed_url = f"{url}?Authorization={auth}"
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expiration_seconds)
    return signed_url, expires_at

