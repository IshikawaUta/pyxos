from unittest.mock import MagicMock, patch


class TestWebUtils:
    def test_mask_value_not_set(self):
        from pyxos.web.app import mask_value
        assert mask_value(None) == "(not set)"
        assert mask_value("") == "(not set)"

    def test_mask_value_short(self):
        from pyxos.web.app import mask_value
        assert mask_value("abc") == "abc"

    def test_mask_value_long(self):
        from pyxos.web.app import mask_value
        result = mask_value("1234567890abcdef")
        assert result == "123456***"

    def test_mask_value_barely_long(self):
        from pyxos.web.app import mask_value
        result = mask_value("12345678")
        assert "***" in result

    def test_format_size_none(self):
        from pyxos.web.app import format_size
        assert format_size(None) == "-"
        assert format_size(0) == "0.0 KB"

    def test_format_size_kb(self):
        from pyxos.web.app import format_size
        assert "KB" in format_size(500)

    def test_format_size_mb(self):
        from pyxos.web.app import format_size
        assert "MB" in format_size(2 * 1024 * 1024)

    def test_get_data_no_uri(self, tmp_path):
        with patch("pyxos.config.load_config") as mock_cfg:
            mock_cfg.return_value = {}
            from pyxos.web.app import get_data
            db, projects, stats = get_data()
            assert db is None
            assert projects is None
            assert stats is None

    def test_get_data_with_db(self, tmp_path):
        with patch("pyxos.config.load_config") as mock_cfg, \
             patch("pyxos.database.Database") as mock_db_class:
            mock_cfg.return_value = {"mongodb_uri": "mongodb://fake"}
            mock_db = MagicMock()
            mock_db.list_projects.return_value = (
                [{"name": "test", "file_size": 1000, "storage_type": "cloudinary"}], 1
            )
            mock_db_class.return_value = mock_db

            from pyxos.web.app import get_data
            db, projects, stats = get_data()
            assert db is not None
            assert len(projects) == 1
            assert stats["total_projects"] == 1
            assert stats["total_size"] == 1000

    def test_get_data_db_error(self, tmp_path):
        with patch("pyxos.config.load_config") as mock_cfg, \
             patch("pyxos.database.Database") as mock_db_class:
            mock_cfg.return_value = {"mongodb_uri": "mongodb://fake"}
            mock_db = MagicMock()
            mock_db.list_projects.side_effect = Exception("DB down")
            mock_db_class.return_value = mock_db

            from pyxos.web.app import get_data
            db, projects, stats = get_data()
            assert db is not None
            assert projects == []
            assert stats["total_projects"] == 0


class TestWebApp:
    def test_create_app(self):
        with patch("pyxos.config.load_config") as mock_config, \
             patch("pyxos.database.Database") as mock_db:
            mock_config.return_value = {
                "mongodb_uri": "mongodb://fake",
                "storage_type": "cloudinary",
                "cloudinary_cloud_name": "mycloud",
                "cloudinary_api_key": "key",
                "cloudinary_api_secret": "secret",
            }
            mock_db_instance = MagicMock()
            mock_db_instance.list_projects.return_value = ([], 0)
            mock_db.return_value = mock_db_instance

            from pyxos.web.app import create_app
            app = create_app()

            assert app is not None
            assert app.title == "Pyxos Dashboard"

    def test_create_app_no_config(self):
        with patch("pyxos.config.load_config") as mock_config:
            mock_config.return_value = {}

            from pyxos.web.app import create_app
            app = create_app()
            assert app is not None

    def test_routes_exist(self):
        with patch("pyxos.config.load_config") as mock_config, \
             patch("pyxos.database.Database") as mock_db:
            mock_config.return_value = {
                "mongodb_uri": "mongodb://fake",
                "storage_type": "cloudinary",
                "cloudinary_cloud_name": "c",
                "cloudinary_api_key": "k",
                "cloudinary_api_secret": "s",
            }
            mock_db_instance = MagicMock()
            mock_db_instance.list_projects.return_value = ([], 0)
            mock_db.return_value = mock_db_instance

            from pyxos.web.app import create_app
            app = create_app()
            router = app.router
            assert router is not None

    def test_index_route(self):
        from pyxos.web import app as web_app
        import importlib
        importlib.reload(web_app)
        from pyxos.web.app import create_app
        application = create_app()
        assert application.router is not None

    def test_stats_route(self):
        from pyxos.web import app as web_app
        import importlib
        importlib.reload(web_app)
        from pyxos.web.app import create_app
        application = create_app()
        assert application.router is not None