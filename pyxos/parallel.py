import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import urllib.request
import urllib.error
from rich.console import Console

console = Console()

CHUNK_SIZE_B2 = 50 * 1024 * 1024
MIN_CHUNK_SIZE = 1024 * 1024


def parallel_upload(archive_path, project_name, storage_type):
    if storage_type != "b2":
        from pyxos.storage import upload_project
        return upload_project(archive_path, project_name)
    return _b2_parallel_upload(archive_path, project_name)


def _b2_parallel_upload(archive_path, project_name):
    from pyxos.storage import _b2_bucket
    from b2sdk.v2 import UploadSourceLocalFile

    archive_path = Path(archive_path)
    file_size = archive_path.stat().st_size

    b2_file_name = f"pyxos/{project_name}.zip"

    if file_size <= CHUNK_SIZE_B2:
        from pyxos.storage import upload_project
        return upload_project(archive_path, project_name)

    tmpdir = Path(tempfile.mkdtemp())
    try:
        parts = _split_file(archive_path, tmpdir, CHUNK_SIZE_B2, project_name)
        num_parts = len(parts)

        with console.status(f"[cyan]Uploading {num_parts} parallel chunks to B2...[/cyan]"):

            def upload_part(index, part_path):
                part_name = f"{b2_file_name}.part{index + 1:04d}"
                _b2_bucket.upload(
                    UploadSourceLocalFile(str(part_path)),
                    part_name,
                )
                return part_name

            with ThreadPoolExecutor(max_workers=min(4, num_parts)) as executor:
                futures = {}
                for i, part_path in enumerate(parts):
                    futures[executor.submit(upload_part, i, part_path)] = i

                for future in as_completed(futures):
                    i = futures[future]
                    try:
                        future.result()
                    except Exception:
                        for f in futures:
                            f.cancel()
                        raise

        manifest = {
            "name": b2_file_name,
            "parts": num_parts,
            "size": file_size,
        }
        import json
        manifest_bytes = json.dumps(manifest).encode("utf-8")
        manifest_path = tmpdir / "manifest.json"
        manifest_path.write_bytes(manifest_bytes)
        _b2_bucket.upload(
            UploadSourceLocalFile(str(manifest_path)),
            f"{b2_file_name}.manifest",
        )

        url = _b2_bucket.get_download_url(f"{b2_file_name}.part0001")
        return url, b2_file_name

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _split_file(file_path, dest_dir, chunk_size, project_name):
    parts = []
    chunk_index = 0
    with open(file_path, "rb") as src:
        while True:
            data = src.read(chunk_size)
            if not data:
                break
            part_path = dest_dir / f"{project_name}.part{chunk_index:04d}"
            with open(part_path, "wb") as part_f:
                part_f.write(data)
            parts.append(part_path)
            chunk_index += 1
    return parts


def parallel_download(url, dest_path, num_workers=4):
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        return _parallel_range_download(url, dest_path, num_workers)
    except Exception:
        return _sequential_download(url, dest_path)


def _parallel_range_download(url, dest_path, num_workers=4):
    head_req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(head_req, timeout=30) as response:
        content_length = int(response.headers.get("Content-Length", 0))
        accepts_ranges = response.headers.get("Accept-Ranges", "").lower() == "bytes"

    if not content_length or not accepts_ranges:
        return _sequential_download(url, dest_path)

    chunk_size = max(MIN_CHUNK_SIZE, content_length // num_workers)
    ranges = []
    start = 0
    while start < content_length:
        end = min(start + chunk_size - 1, content_length - 1)
        ranges.append((start, end))
        start = end + 1

    tmpdir = Path(tempfile.mkdtemp())
    chunk_files = []

    try:

        def download_chunk(start_byte, end_byte, index):
            req = urllib.request.Request(url)
            req.add_header("Range", f"bytes={start_byte}-{end_byte}")
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = resp.read()
            chunk_path = tmpdir / f"chunk_{index:04d}"
            chunk_path.write_bytes(data)
            return chunk_path

        with console.status(f"[cyan]Parallel download with {num_workers} workers...[/cyan]"):
            with ThreadPoolExecutor(max_workers=min(num_workers, len(ranges))) as executor:
                futures = {}
                for i, (s, e) in enumerate(ranges):
                    futures[executor.submit(download_chunk, s, e, i)] = i

                for future in as_completed(futures):
                    i = futures[future]
                    try:
                        chunk_files.append((i, future.result()))
                    except Exception:
                        for f in futures:
                            f.cancel()
                        raise

        chunk_files.sort(key=lambda x: x[0])
        with open(dest_path, "wb") as out:
            for _, chunk_path in chunk_files:
                out.write(chunk_path.read_bytes())

        return dest_path
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _sequential_download(url, dest_path):
    with console.status("[cyan]Sequential download...[/cyan]"):
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=300) as response:
            data = response.read()
    dest_path.write_bytes(data)
    return dest_path
