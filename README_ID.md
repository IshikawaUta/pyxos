# Pyxos

[English](README.md)

[![CI](https://github.com/IshikawaUta/pyxos/actions/workflows/ci.yml/badge.svg)](https://github.com/IshikawaUta/pyxos/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

CLI tool untuk manajemen project — push, pull, list, update, dan delete project antara lokal, MongoDB Atlas, dan Cloudinary atau Backblaze B2.

## Prasyarat

- Python 3.10+
- MongoDB Atlas cluster ([free tier M0](https://www.mongodb.com/atlas))
- **Salah satu** storage backend:
  - Cloudinary ([free tier](https://cloudinary.com)) — max **10 MB** per file
  - Backblaze B2 ([free 10 GB](https://www.backblaze.com/b2/cloud-storage.html)) — **no file size limit**, cocok untuk project besar

## Instalasi

### pipx

```bash
pipx install git+https://github.com/IshikawaUta/pyxos.git
```

### Dari source

```bash
git clone https://github.com/IshikawaUta/pyxos.git
cd pyxos
pipx install .
```

Atau via virtual environment:

```bash
git clone https://github.com/IshikawaUta/pyxos.git
cd pyxos
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Verifikasi:

```bash
pyxos --version
```

## Konfigurasi

### Metode 1: Interaktif (Rekomendasi)

```bash
pyxos init
```

Prompt akan meminta:
1. **Storage backend** — `cloudinary` atau `b2`
2. **MongoDB Atlas URI** (disembunyikan)
3. Credential storage sesuai pilihan (Cloudinary: Cloud Name, API Key, API Secret; B2: Bucket Name, Application Key ID, Application Key)

### Metode 2: Environment Variables

**Cloudinary:**
```bash
export PYXOS_STORAGE_TYPE=cloudinary
export PYXOS_MONGODB_URI="mongodb+srv://user:pass@cluster.mongodb.net/"
export PYXOS_CLOUDINARY_CLOUD_NAME="nama-cloud"
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

### Metode 3: File `.env`

Buat file `.env` di direktori kerja (lihat `.env.example`):

**Cloudinary:**
```
storage_type=cloudinary
mongodb_uri=mongodb+srv://user:pass@cluster.mongodb.net/
cloudinary_cloud_name=nama-cloud
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

### Prioritas Konfigurasi

1. `~/.pyxos/config.json` (dari `pyxos init`)
2. File `.env` di direktori kerja
3. Environment variable (`PYXOS_*`)

### Verifikasi Koneksi

```bash
pyxos check
```

### Melihat Konfigurasi

```bash
pyxos config show
```

Menampilkan sumber konfigurasi (`config.json` / `.env` / env vars), storage backend, URI, dan kredensial (disensor).

### Menghapus Konfigurasi

```bash
pyxos config reset
```

Menghapus `~/.pyxos/config.json` **dan** menghapus kunci Pyxos dari file `.env`. Environment variable (`PYXOS_*`) harus dibersihkan manual.

### Ganti Storage Backend

Jalankan `pyxos init` ulang untuk beralih antara Cloudinary dan B2. Project yang sudah di-push akan tetap bisa di-pull (masing-masing simpan `storage_type` di metadata database).

---

## Arsitektur

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
│   ├── config.py       # Konfigurasi, archive .zip, filter pola
│   ├── database.py     # MongoDB Atlas CRUD
│   ├── storage.py      # Cloudinary + B2 upload/download/delete/resume
│   ├── cache.py        # Cache lokal untuk daftar offline
│   ├── crypto.py       # AES-256-CBC encrypt/decrypt (streaming)
│   ├── parallel.py     # Parallel upload/download dengan chunking
│   └── web/
│       ├── __init__.py
│       ├── app.py          # Dashboard web (opsional)
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
    ├── conftest.py
    ├── test_cache.py
    ├── test_cli.py
    ├── test_config.py
    ├── test_crypto.py
    ├── test_database.py
    ├── test_parallel.py
    ├── test_storage.py
    └── test_web.py
```

### Alur Data

```
push:  [lokal] ──zip──▶ [tmp] ──upload──▶ [Cloudinary / B2]
                          │                        │
                          └──metadata─────────────▶ [MongoDB Atlas]

pull:  [MongoDB Atlas] ──metadata──▶ [query]
                          │
                          └──public_id──▶ [Cloudinary / B2] ──download──▶ [lokal]
```

---

## Perintah (Commands)

### `pyxos push` — Upload project ke cloud

```bash
pyxos push [PATH] [OPTIONS]
```

| Flag | Singkat | Deskripsi |
|---|---|---|
| `--name` | `-n` | Nama project (default: nama direktori) |
| `--description` | `-d` | Deskripsi project |
| `--tags` | `-t` | Tag dipisah koma, contoh: `"python,web,api"` |
| `--version` | `-v` | Versi project (default: `1.0.0`) |
| `--force` | `-f` | Timpa project yang sudah ada |
| `--dry-run` | | Preview file yang akan dipaket, tanpa upload |
| `--no-confirm-size` | | Skip konfirmasi untuk project >50 MB |
| `--exclude` | `-e` | Pattern tambahan untuk dikecualikan (bisa diulang) |
| `--include` | `-i` | Paksa sertakan file meski kena exclude (bisa diulang) |
| `--encrypt` | | Enkripsi arsip sebelum upload (akan diminta password) |

> **Catatan:** Cloudinary free tier membatasi upload ke **10 MB**. Project >10 MB akan otomatis ditolak dengan pesan jelas. Gunakan B2 storage untuk project besar.

**Contoh:**

```bash
# Push direktori saat ini
pyxos push .

# Push dengan metadata lengkap
pyxos push ./myapp -n MyApp -d "Aplikasi web" -t "python,flask" -v 2.0.0

# Timpa project yang sudah ada
pyxos push . --force

# Preview tanpa upload
pyxos push . --dry-run

# Exclude file log, kecuali error.log
pyxos push . -e "*.log" -i "error.log"
```

### `pyxos pull` — Download project dari cloud

```bash
pyxos pull [QUERY] [OPTIONS]
```

`QUERY` bisa berupa nama project atau ID. Jika dikosongkan, tampil daftar interaktif.

| Flag | Singkat | Deskripsi |
|---|---|---|
| `--output` | `-o` | Direktori output (default: `.`) |
| `--force` | `-f` | Timpa direktori jika sudah ada |
| `--decrypt` | | Dekripsi arsip setelah download (akan diminta password) |

**Contoh:**

```bash
# Pilih dari daftar interaktif
pyxos pull

# Pull berdasarkan nama
pyxos pull MyApp

# Pull ke direktori spesifik
pyxos pull MyApp -o ~/projects

# Timpa jika sudah ada
pyxos pull MyApp --force
```

### `pyxos list` — Daftar semua project

```bash
pyxos list [OPTIONS]
```

| Flag | Singkat | Deskripsi |
|---|---|---|
| `--search` | `-s` | Cari berdasarkan nama atau deskripsi (case-insensitive) |
| `--tag` | `-t` | Filter berdasarkan tag (bisa diulang untuk AND) |
| `--page` | `-p` | Nomor halaman (default: 1) |
| `--per-page` | | Hasil per halaman (default: 20) |
| `--json` | | Output dalam format JSON |
| `--no-cache` | | Skip cache, paksa data fresh dari database |
| `--offline` | | Gunakan cache saja, tanpa koneksi database |

**Contoh:**

```bash
# Semua project
pyxos list

# Cari project mengandung kata "api"
pyxos list -s api

# Filter tag spesifik
pyxos list -t python -t web

# Halaman berikutnya
pyxos list -p 2

# Output JSON untuk scripting
pyxos list --json
```

### `pyxos info` — Detail satu project

```bash
pyxos info [QUERY]
```

Menampilkan: ID, versi, deskripsi, tags, jumlah file, ukuran, local path, storage URL, created_at, updated_at.

```bash
# Pilih interaktif
pyxos info

# Berdasarkan nama
pyxos info MyApp
```

### `pyxos update` — Update metadata atau re-upload

```bash
pyxos update QUERY [OPTIONS]
```

| Flag | Singkat | Deskripsi |
|---|---|---|
| `--name` | `-n` | Nama baru |
| `--description` | `-d` | Deskripsi baru |
| `--tags` | `-t` | Tag baru |
| `--version` | `-v` | Versi baru |
| `--reupload` | `-r` | Re-upload file dari local path yang tersimpan |

**Contoh:**

```bash
# Update metadata saja
pyxos update MyApp -d "Deskripsi baru" -v 2.1.0

# Update metadata + re-upload file
pyxos update MyApp -r -v 2.1.0

# Rename project
pyxos update MyApp -n NewName
```

### `pyxos delete` — Hapus project

```bash
pyxos delete [QUERY] [OPTIONS]
```

| Flag | Singkat | Deskripsi |
|---|---|---|
| `--yes` | `-y` | Skip konfirmasi |
| `--all` | | Hapus SEMUA project (wajib `--yes`) |

Menghapus dari storage **dan** MongoDB Atlas.

```bash
# Interaktif
pyxos delete

# Hapus berdasarkan nama
pyxos delete MyApp

# Langsung tanpa konfirmasi
pyxos delete MyApp -y

# Hapus semua project
pyxos delete --all --yes
```

### `pyxos open` — Buka di browser

```bash
pyxos open [QUERY]
```

Membuka storage URL project di browser default.

### `pyxos check` — Cek koneksi

```bash
pyxos check
```

Verifikasi koneksi MongoDB Atlas dan storage backend (Cloudinary/B2) dengan spinner loading.

### `pyxos diff` — Bandingkan lokal vs remote

```bash
pyxos diff [QUERY] [OPTIONS]
```

Menampilkan perbedaan file antara direktori project lokal dan versi remote.

| Flag | Singkat | Deskripsi |
|---|---|---|
| `--path` | `-p` | Override path project lokal |

> **Enkripsi:** Gunakan `--encrypt` pada `push` untuk enkripsi arsip sebelum upload, dan `--decrypt` pada `pull` untuk dekripsi setelah download. Keduanya meminta password secara interaktif.

### `pyxos share` — Buat link share

```bash
pyxos share [QUERY] [OPTIONS]
```

Membuat link download sementara untuk project.

| Flag | Singkat | Deskripsi |
|---|---|---|
| `--expires` | `-e` | Durasi kedaluwarsa dalam detik (default: 3600) |
| `--clipboard` | `-c` | Salin URL ke clipboard |

### `pyxos stats` — Statistik project

```bash
pyxos stats [OPTIONS]
```

Menampilkan statistik agregat: total project, total ukuran, backend storage, distribusi tag.

### `pyxos rollback` — Kembali ke versi sebelumnya

```bash
pyxos rollback QUERY [OPTIONS]
```

Rollback ke versi project sebelumnya yang tersimpan di version history.

| Flag | Singkat | Deskripsi |
|---|---|---|
| `--to` | | Rollback ke versi spesifik |

### `pyxos clone` — Clone project

```bash
pyxos clone QUERY [OPTIONS]
```

Clone/download project remote ke direktori lokal baru.

| Flag | Singkat | Deskripsi |
|---|---|---|
| `--output` | `-o` | Direktori output |

### `pyxos tags` — Kelola tag project

```bash
pyxos tags [QUERY] [OPTIONS]
```

Tambah, hapus, atau tampilkan tag project.

| Flag | Singkat | Deskripsi |
|---|---|---|
| `--add` | `-a` | Tambah tag (dipisah koma) |
| `--remove` | `-r` | Hapus tag (dipisah koma) |
| `--list` | `-l` | Tampilkan semua tag |

### `pyxos config` — Kelola konfigurasi

```bash
pyxos config [COMMAND]
```

Sub-perintah:
- `pyxos config show` — Tampilkan konfigurasi (kredensial disensor)
- `pyxos config reset` — Reset konfigurasi

### `pyxos export` — Ekspor database

```bash
pyxos export [QUERY] [OPTIONS]
```

Ekspor metadata project ke JSON.

| Flag | Singkat | Deskripsi |
|---|---|---|
| `--all` | | Ekspor semua project |
| `--output` | `-o` | Path file output |

### `pyxos import` — Impor database

```bash
pyxos import FILE [OPTIONS]
```

Impor project dari file JSON hasil ekspor.

### `pyxos watch` — Pantau dan auto-push

```bash
pyxos watch [PATH] [OPTIONS]
```

Pantau direktori untuk perubahan dan push otomatis. Gunakan `watchfiles` jika terinstal, fallback ke polling.

| Flag | Singkat | Deskripsi |
|---|---|---|
| `--interval` | `-i` | Interval debounce dalam detik (default: 3.0) |
| `--name` | `-n` | Nama project |

### `pyxos web` — Dashboard web

```bash
pyxos web [OPTIONS]
```

Jalankan dashboard web lokal untuk browsing dan mengelola project.

| Flag | Singkat | Deskripsi |
|---|---|---|
| `--host` | | Host listen (default: 127.0.0.1) |
| `--port` | `-p` | Port listen (default: 8765) |

### `pyxos completion` — Shell completion

```bash
pyxos completion [SHELL]
```

Generate script shell completion. Mendukung `bash`, `zsh`, `fish`.

```bash
# Zsh
eval "$(pyxos completion zsh)"

# Bash
eval "$(pyxos completion bash)"
```

---

## File Exclusion

### Default Exclude Patterns

Saat melakukan `push`, file/direktori berikut otomatis dikecualikan:

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

Buat file `.pyxosignore` di root project untuk menambah pattern kustom:

```
# .pyxosignore - custom exclusions
*.log
temp/
secrets.json
```

Baris dengan `#` adalah komentar.

### CLI Override

```bash
# Tambah exclude pattern via CLI
pyxos push . -e "*.md" -e "docs/"

# Paksa include file yang kena exclude
pyxos push . -e "*.py" -i "main.py"
```

---

## Database Schema

Koleksi: `pyxos.projects`

| Field | Tipe | Deskripsi |
|---|---|---|
| `_id` | ObjectId | Auto-generated |
| `name` | String | Nama project (unique) |
| `description` | String | Deskripsi project |
| `tags` | Array[String] | Tag untuk filter |
| `version` | String | Versi project |
| `storage_type` | String | `cloudinary` atau `b2` |
| `storage_url` | String | URL download dari storage |
| `storage_public_id` | String | Public ID / file path (Cloudinary: `pyxos/{name}`, B2: `pyxos/{name}.zip`) |
| `local_path` | String | Path lokal saat push |
| `file_size` | Int | Ukuran arsip dalam bytes |
| `file_count` | Int | Jumlah file dalam arsip |
| `encrypted` | Bool | Apakah arsip terenkripsi |
| `exclude_patterns` | Array[String] | Pola filter yang digunakan saat push |
| `created_at` | DateTime | Waktu dibuat (UTC) |
| `updated_at` | DateTime | Waktu diupdate (UTC) |

> **Catatan:** Field `cloudinary_url` dan `cloudinary_public_id` masih didukung sebagai fallback untuk project lama (backward compatible). Project baru akan ditulis dengan `storage_url` / `storage_public_id`.

---

## Dependensi

| Package | Versi | Kegunaan |
|---|---|---|
| [click](https://click.palletsprojects.com) | >=8.1 | CLI framework |
| [rich](https://rich.readthedocs.io) | >=13 | Tabel, panel, progress bar, spinner |
| [pymongo](https://pymongo.readthedocs.io) | >=4.6 | MongoDB driver (+SRV support) |
| [cloudinary](https://cloudinary.com/documentation/python_integration) | >=1.36 | Cloudinary SDK |
| [b2sdk](https://github.com/Backblaze/b2-sdk-python) | >=2.0 | Backblaze B2 SDK |
| [cryptography](https://cryptography.io) | >=41 | AES-256-CBC enkripsi/dekripsi |

### Dependensi Opsional

| Extra | Package | Kegunaan |
|---|---|---|
| `[web]` | [fenrir-framework](https://github.com/IshikawaUta/fenrir) | Dashboard web (`pyxos web`) |
| `[watch]` | [watchfiles](https://github.com/samuelcolvin/watchfiles) | File watching efisien (`pyxos watch`) |

```bash
pip install "pyxos[web,watch]"
```

---

## Penanganan Error

Pyxos menggunakan `sys.excepthook` untuk menangkap exception yang tidak tertangani dan menampilkan pesan ramah tanpa traceback:

- `KeyboardInterrupt` (Ctrl+C) → "Cancelled."
- `click.Abort` → silent exit
- `click.UsageError` → pesan error merah
- HTTP errors (4xx/5xx) → pesan deskriptif dengan kode status
- Error storage → pesan error spesifik backend
- Error database → pesan error koneksi dan query
- Exception lainnya → pesan error merah dengan detail

---

## Indikator Progress

- **Upload**: progress bar dengan kecepatan transfer (B2: upload parallel chunked untuk file >50 MB)
- **Download**: progress bar dengan dukungan resume chunked (Cloudinary dan B2)
- **Enkripsi/Dekripsi**: pemrosesan streaming — hemat memori untuk ukuran file berapa pun
- **List/Check**: spinner loading saat query database
- **Peringatan ukuran**: konfirmasi untuk project >50 MB
- **Watch mode**: tampilan live dengan auto-push berbasis debounce

---

## Cache

Pyxos menyimpan cache lokal dari daftar project untuk penggunaan offline:

```bash
# Data fresh + hapus cache lama
pyxos list --no-cache

# Cache saja (mode offline)
pyxos list --offline

# Info dengan data fresh
pyxos info MyApp --no-cache
```

Cache disimpan di `~/.pyxos/cache.json` dengan jendela kesegaran default. Flag `--no-cache` akan melewati pemuatan cache DAN menghapus file cache yang ada.

---

## Dashboard Web

```bash
# Install dengan dependensi web opsional
pip install "pyxos[web]"

# Jalankan dashboard
pyxos web --host 0.0.0.0 --port 8765
```

Jelajahi project, lihat statistik, dan kelola metadata dari antarmuka web. Dibangun dengan Fenrir.

---

## Lisensi

MIT — lihat file [LICENSE](LICENSE).
