"""Web app route handler tests using fenrir test_client (async)."""

import asyncio
import importlib
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


class TestWebRouteHandlers:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        from pyxos.web import app as web_app
        importlib.reload(web_app)

        now = datetime.now(timezone.utc)
        self.mock_db = MagicMock()
        self.mock_db.list_projects.return_value = ([
            {"name": "proj1", "file_size": 1024, "storage_type": "cloudinary",
             "updated_at": now, "created_at": now, "version": "1.0",
             "tags": ["python"], "storage_public_id": "px/p1",
             "description": "test desc"},
        ], 1)
        self.mock_db.get_project.return_value = {
            "_id": "507f1f77bcf86cd799439011",
            "name": "proj1", "file_size": 1024, "storage_type": "cloudinary",
            "updated_at": now, "created_at": now, "version": "1.0",
            "tags": ["python"], "storage_public_id": "px/p1",
        }

        monkeypatch.setattr("pyxos.config.load_config", lambda: {
            "mongodb_uri": "mongodb://fake",
            "storage_type": "cloudinary",
            "cloudinary_cloud_name": "c",
            "cloudinary_api_key": "k",
            "cloudinary_api_secret": "s",
        })
        monkeypatch.setattr("pyxos.database.Database", lambda uri, **kw: self.mock_db)
        monkeypatch.setattr("pyxos.storage.init_storage", lambda c: None)
        monkeypatch.setattr("pyxos.storage.delete_project", lambda p: None)

    def _client(self):
        from pyxos.web.app import create_app
        return create_app().test_client()

    def _get(self, path):
        return asyncio.run(self._client().get(path))

    def _post(self, path):
        return asyncio.run(self._client().post(path))

    def test_index_returns_200(self):
        resp = self._get("/")
        assert resp.status_code == 200

    def test_projects_returns_200(self):
        resp = self._get("/projects")
        assert resp.status_code == 200

    def test_projects_with_search(self):
        resp = self._get("/projects?search=proj")
        assert resp.status_code == 200

    def test_project_detail(self):
        resp = self._get("/projects/507f1f77bcf86cd799439011")
        assert resp.status_code == 200

    def test_project_detail_not_found(self):
        self.mock_db.get_project.return_value = None
        resp = self._get("/projects/nonexistent")
        assert resp.status_code == 404

    def test_config_returns_200(self):
        resp = self._get("/config")
        assert resp.status_code == 200

    def test_stats_returns_200(self):
        resp = self._get("/stats")
        assert resp.status_code == 200

    def test_delete_project(self):
        now = datetime.now(timezone.utc)
        self.mock_db.get_project.return_value = {
            "_id": "507f1f77bcf86cd799439011",
            "name": "proj1", "storage_public_id": "px/p1",
            "updated_at": now, "created_at": now,
        }
        resp = self._post("/projects/delete/507f1f77bcf86cd799439011")
        assert resp.status_code in (200, 302, 303)

    def test_error_page_no_config(self, monkeypatch):
        monkeypatch.setattr("pyxos.config.load_config", lambda: {})
        resp = self._get("/")
        assert resp.status_code == 200

    def test_format_size_negative(self):
        from pyxos.web.app import format_size

        assert format_size(-1) == "-"
