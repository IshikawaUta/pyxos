import os
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def temp_project(tmp_path):
    proj = tmp_path / "myproject"
    proj.mkdir()
    (proj / "main.py").write_text("print('hello')")
    (proj / "utils.py").write_text("def util(): pass")
    (proj / "README.md").write_text("# My Project")
    (proj / ".git").mkdir()
    (proj / ".git" / "HEAD").write_text("ref: main")
    (proj / "__pycache__").mkdir()
    (proj / "__pycache__" / "main.cpython-313.pyc").write_text("cached")
    (proj / ".env").write_text("SECRET=123")
    return proj


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    config_dir = tmp_path / ".pyxos"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    monkeypatch.setattr("pyxos.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("pyxos.config.CONFIG_FILE", config_file)
    return config_file


@pytest.fixture
def clean_env(monkeypatch):
    for k in ("PYXOS_MONGODB_URI", "PYXOS_CLOUDINARY_CLOUD_NAME",
              "PYXOS_CLOUDINARY_API_KEY", "PYXOS_CLOUDINARY_API_SECRET"):
        monkeypatch.setenv(k, "")


@pytest.fixture
def sample_config(config_file, clean_env):
    data = {
        "mongodb_uri": "mongodb+srv://test:pass@cluster.mongodb.net/",
        "cloudinary_cloud_name": "mycloud",
        "cloudinary_api_key": "123456789",
        "cloudinary_api_secret": "abc123xyz",
    }
    config_file.write_text(json.dumps(data))
    return data


@pytest.fixture
def mock_mongo_client():
    """Mock MongoClient to allow Database tests."""
    with patch("pyxos.database.MongoClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.admin.command.return_value = {"ok": 1}

        mock_collection = MagicMock()
        mock_db = MagicMock()
        type(mock_db).__getitem__ = MagicMock(return_value=mock_collection)
        mock_client.pyxos = mock_db

        mock_client_cls.return_value = mock_client

        from pyxos.database import Database
        db = Database("mongodb://fake")
        yield db, mock_client, mock_collection


@pytest.fixture
def mock_cloudinary():
    """Mock cloudinary module functions."""
    with patch("cloudinary.uploader.upload") as mock_upload, \
         patch("cloudinary.uploader.destroy") as mock_destroy, \
         patch("cloudinary.api.ping") as mock_ping, \
         patch("cloudinary.config") as mock_config, \
         patch("pyxos.storage.cloudinary_url") as mock_url:
        mock_upload.return_value = {
            "secure_url": "https://cloudinary.com/fake.zip",
            "public_id": "pyxos/testproj",
        }
        mock_ping.return_value = True
        mock_url.return_value = ("https://cloudinary.com/fake.zip", None)
        yield {
            "upload": mock_upload,
            "destroy": mock_destroy,
            "ping": mock_ping,
            "config": mock_config,
        }
