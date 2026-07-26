"""GUI tests for Pyxos (PySide6)."""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from unittest.mock import MagicMock, patch

import pytest

PySide6 = pytest.importorskip("PySide6")
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402


@pytest.fixture(scope="session")
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    app.setStyle("Fusion")
    return app


def _mock_config():
    return {
        "mongodb_uri": "mongodb+srv://test:pass@cluster.mongodb.net/",
        "storage_type": "cloudinary",
        "cloudinary_cloud_name": "mycloud",
        "cloudinary_api_key": "123",
        "cloudinary_api_secret": "abc",
    }


class TestFormatSize:
    def test_bytes(self):
        from pyxos.gui.main import _format_size

        assert _format_size(500) == "500.0 B"

    def test_kb(self):
        from pyxos.gui.main import _format_size

        assert _format_size(2048) == "2.0 KB"

    def test_mb(self):
        from pyxos.gui.main import _format_size

        assert _format_size(5_242_880) == "5.0 MB"

    def test_gb(self):
        from pyxos.gui.main import _format_size

        assert _format_size(1_073_741_824 * 2) == "2.0 GB"

    def test_zero(self):
        from pyxos.gui.main import _format_size

        assert _format_size(0) == "0.0 B"

    def test_none(self):
        from pyxos.gui.main import _format_size

        assert _format_size(None) == "0 B"


class TestMainWindow:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        db = MagicMock()
        db.list_projects.return_value = ([], 0)
        db.get_project_by_name.return_value = None
        monkeypatch.setattr("pyxos.gui.main.load_config", _mock_config)
        monkeypatch.setattr("pyxos.gui.main.save_config", lambda c: None)
        monkeypatch.setattr("pyxos.gui.main.delete_config", lambda: None)
        monkeypatch.setattr("pyxos.gui.main._run_storage", lambda: True)
        monkeypatch.setattr(
            "pyxos.storage.init_storage", lambda c: None
        )

        with patch("pyxos.gui.main.Database", return_value=db):
            yield

    def test_window_launches(self, _qapp, qtbot):
        from pyxos.gui.main import gui_launch

        app = QApplication.instance()
        QTimer.singleShot(100, app.quit)
        gui_launch()

    def test_sidebar_items(self, _qapp):
        from pyxos.gui.main import gui_launch

        app = QApplication.instance()
        found = []

        def _check():
            for w in app.topLevelWidgets():
                nav = w.findChildren(PySide6.QtWidgets.QListWidget)
                if nav:
                    found.extend(
                        nav[0].item(i).text()
                        for i in range(nav[0].count())
                    )
                    break
            app.quit()

        QTimer.singleShot(100, _check)
        gui_launch()

        assert "Dashboard" in found
        assert "Projects" in found
        assert "Push" in found
        assert "Pull" in found
        assert "Share" in found
        assert "Statistics" in found
        assert "Watch" in found

    def test_all_pages_created(self, _qapp):
        from pyxos.gui.main import gui_launch

        app = QApplication.instance()

        found = [0]

        def _check():
            for w in app.topLevelWidgets():
                stack = w.findChildren(PySide6.QtWidgets.QStackedWidget)
                if stack:
                    found[0] = stack[0].count()
                    break
            app.quit()

        QTimer.singleShot(100, _check)
        gui_launch()

        assert found[0] >= 8

    def test_share_page_loads(self, _qapp):
        from pyxos.gui.main import gui_launch

        app = QApplication.instance()
        QTimer.singleShot(100, app.quit)
        gui_launch()

    def test_watch_page_has_info(self, _qapp):
        from pyxos.gui.main import gui_launch

        app = QApplication.instance()
        found = [False]

        def _check():
            for w in app.topLevelWidgets():
                edits = w.findChildren(PySide6.QtWidgets.QTextEdit)
                for edit in edits:
                    if "pyxos watch" in edit.toPlainText():
                        found[0] = True
                        break
                if found[0]:
                    break
            app.quit()

        QTimer.singleShot(100, _check)
        gui_launch()

        assert found[0]


class TestConfigDialog:
    def test_config_dialog_no_crash(self, monkeypatch, _qapp):
        """When config is empty, ConfigDialog appears without crashing."""
        monkeypatch.setattr(
            "pyxos.gui.main.load_config", lambda: {}
        )
        monkeypatch.setattr("pyxos.gui.main.save_config", lambda c: None)
        monkeypatch.setattr("pyxos.gui.main.delete_config", lambda: None)
        monkeypatch.setattr("pyxos.gui.main._run_storage", lambda: True)
        monkeypatch.setattr(
            "pyxos.storage.init_storage", lambda c: None
        )

        from pyxos.gui.main import gui_launch

        # Reject dialog immediately to avoid blocks
        original_exec = QDialog.exec
        QDialog.exec = lambda self_dlg, exec_orig=original_exec: 0

        try:
            gui_launch()
        finally:
            QDialog.exec = original_exec

    def test_config_dialog_with_valid_config(self, monkeypatch, _qapp):
        """When config is valid, MainWindow launches instead of dialog."""
        monkeypatch.setattr("pyxos.gui.main.load_config", _mock_config)
        monkeypatch.setattr("pyxos.gui.main.save_config", lambda c: None)
        monkeypatch.setattr("pyxos.gui.main.delete_config", lambda: None)
        monkeypatch.setattr("pyxos.gui.main._run_storage", lambda: True)
        monkeypatch.setattr(
            "pyxos.storage.init_storage", lambda c: None
        )

        from pyxos.gui.main import gui_launch

        app = QApplication.instance()

        found_window = [False]

        def _check():
            for w in app.topLevelWidgets():
                if isinstance(w, PySide6.QtWidgets.QWidget) and not isinstance(
                    w, PySide6.QtWidgets.QDialog
                ):
                    found_window[0] = True
                    break
            app.quit()

        with patch("pyxos.gui.main.Database", return_value=MagicMock()):
            QTimer.singleShot(100, _check)
            gui_launch()

        assert found_window[0]
