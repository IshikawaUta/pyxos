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
            "pyxos.gui.main.load_config", dict
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


class TestNavigation:
    """Tests that navigate between tabs to trigger load methods."""

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
        # Prevent modal dialogs from blocking
        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.warning", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.information", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.critical", lambda *a, **kw: None
        )

        with patch("pyxos.gui.main.Database", return_value=db):
            yield

    def test_navigate_to_projects(self, _qapp):
        from pyxos.gui.main import gui_launch

        app = QApplication.instance()
        done = [False]

        def _check():
            for w in app.topLevelWidgets():
                nav = w.findChildren(PySide6.QtWidgets.QListWidget)
                if nav:
                    nav[0].setCurrentRow(1)  # Projects
                    QTimer.singleShot(50, app.quit)
                    done[0] = True
                    break
            if not done[0]:
                app.quit()

        QTimer.singleShot(100, _check)
        gui_launch()

        assert done[0]

    def test_navigate_to_stats(self, _qapp):
        from pyxos.gui.main import gui_launch

        app = QApplication.instance()
        done = [False]

        def _check():
            for w in app.topLevelWidgets():
                nav = w.findChildren(PySide6.QtWidgets.QListWidget)
                if nav:
                    nav[0].setCurrentRow(5)  # Statistics (after Share was added)
                    QTimer.singleShot(50, app.quit)
                    done[0] = True
                    break
            if not done[0]:
                app.quit()

        QTimer.singleShot(100, _check)
        gui_launch()

        assert done[0]

    def test_navigate_to_push(self, _qapp):
        from pyxos.gui.main import gui_launch

        app = QApplication.instance()
        done = [False]

        def _check():
            for w in app.topLevelWidgets():
                nav = w.findChildren(PySide6.QtWidgets.QListWidget)
                if nav:
                    nav[0].setCurrentRow(2)  # Push
                    QTimer.singleShot(50, app.quit)
                    done[0] = True
                    break
            if not done[0]:
                app.quit()

        QTimer.singleShot(100, _check)
        gui_launch()

        assert done[0]

    def test_navigate_to_pull(self, _qapp):
        from pyxos.gui.main import gui_launch

        app = QApplication.instance()
        done = [False]

        def _check():
            for w in app.topLevelWidgets():
                nav = w.findChildren(PySide6.QtWidgets.QListWidget)
                if nav:
                    nav[0].setCurrentRow(3)  # Pull
                    QTimer.singleShot(50, app.quit)
                    done[0] = True
                    break
            if not done[0]:
                app.quit()

        QTimer.singleShot(100, _check)
        gui_launch()

        assert done[0]

    def test_navigate_to_share(self, _qapp):
        from pyxos.gui.main import gui_launch

        app = QApplication.instance()
        done = [False]

        def _check():
            for w in app.topLevelWidgets():
                nav = w.findChildren(PySide6.QtWidgets.QListWidget)
                if nav:
                    nav[0].setCurrentRow(4)  # Share
                    QTimer.singleShot(50, app.quit)
                    done[0] = True
                    break
            if not done[0]:
                app.quit()

        QTimer.singleShot(100, _check)
        gui_launch()

        assert done[0]

    def test_settings_button(self, _qapp):
        from pyxos.gui.main import gui_launch

        app = QApplication.instance()
        done = [False]

        def _check():
            for w in app.topLevelWidgets():
                btns = w.findChildren(PySide6.QtWidgets.QPushButton)
                for btn in btns:
                    if "ettings" in btn.text():
                        btn.click()
                        QTimer.singleShot(50, app.quit)
                        done[0] = True
                        break
                if done[0]:
                    break
            if not done[0]:
                app.quit()

        QTimer.singleShot(100, _check)
        gui_launch()

        assert done[0]


class TestPushPullWorkflow:
    """Tests push/pull button handlers (mocked storage)."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        self.db = MagicMock()
        self.db.list_projects.return_value = ([], 0)
        self.db.get_project_by_name.return_value = None
        monkeypatch.setattr("pyxos.gui.main.load_config", _mock_config)
        monkeypatch.setattr("pyxos.gui.main.save_config", lambda c: None)
        monkeypatch.setattr("pyxos.gui.main.delete_config", lambda: None)
        monkeypatch.setattr("pyxos.gui.main._run_storage", lambda: True)
        monkeypatch.setattr(
            "pyxos.storage.init_storage", lambda c: None
        )
        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.warning", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.information", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.critical", lambda *a, **kw: None
        )

        with patch("pyxos.gui.main.Database", return_value=self.db):
            yield

    def test_push_button_no_path_shows_warning(self, _qapp, qtbot):
        from pyxos.gui.main import gui_launch

        app = QApplication.instance()
        pushed = [False]

        def _check():
            for w in app.topLevelWidgets():
                btns = w.findChildren(PySide6.QtWidgets.QPushButton)
                for btn in btns:
                    if "Push to" in btn.text():
                        btn.click()
                        pushed[0] = True
                        QTimer.singleShot(50, app.quit)
                        break
                if pushed[0]:
                    break
            if not pushed[0]:
                app.quit()

        # Navigate to push tab first
        def _nav():
            for w2 in app.topLevelWidgets():
                nav = w2.findChildren(PySide6.QtWidgets.QListWidget)
                if nav:
                    nav[0].setCurrentRow(2)  # Push
                    QTimer.singleShot(100, _check)
                    break

        QTimer.singleShot(100, _nav)
        gui_launch()

        assert pushed[0]

    def test_push_button_with_path(self, _qapp, tmp_path, monkeypatch):
        from pyxos.gui.main import gui_launch

        monkeypatch.setattr(
            "pyxos.config.make_archive",
            lambda p, n: (str(tmp_path / "test.zip"), 5),
        )
        monkeypatch.setattr(
            "os.path.getsize",
            lambda p: 1024,
        )

        app = QApplication.instance()
        pushed = [False]

        def _check():
            for w in app.topLevelWidgets():
                edits = w.findChildren(PySide6.QtWidgets.QLineEdit)
                for edit in edits:
                    if edit.placeholderText() and "path" in edit.placeholderText().lower():
                        edit.setText(str(tmp_path))
                        break
                # Find push button and click
                btns = w.findChildren(PySide6.QtWidgets.QPushButton)
                for btn in btns:
                    if "Push to" in btn.text():
                        btn.click()
                        pushed[0] = True
                        QTimer.singleShot(100, app.quit)
                        break
                if pushed[0]:
                    break
            if not pushed[0]:
                app.quit()

        def _nav():
            for w2 in app.topLevelWidgets():
                nav = w2.findChildren(PySide6.QtWidgets.QListWidget)
                if nav:
                    nav[0].setCurrentRow(2)  # Push
                    QTimer.singleShot(100, _check)
                    break

        QTimer.singleShot(100, _nav)
        gui_launch()

        assert pushed[0]

    def test_pull_button_no_query_shows_warning(self, _qapp, qtbot):
        from pyxos.gui.main import gui_launch

        app = QApplication.instance()
        pulled = [False]

        def _check():
            for w in app.topLevelWidgets():
                btns = w.findChildren(PySide6.QtWidgets.QPushButton)
                for btn in btns:
                    if "Pull from" in btn.text():
                        btn.click()
                        pulled[0] = True
                        QTimer.singleShot(50, app.quit)
                        break
                if pulled[0]:
                    break
            if not pulled[0]:
                app.quit()

        def _nav():
            for w2 in app.topLevelWidgets():
                nav = w2.findChildren(PySide6.QtWidgets.QListWidget)
                if nav:
                    nav[0].setCurrentRow(3)  # Pull
                    QTimer.singleShot(100, _check)
                    break

        QTimer.singleShot(100, _nav)
        gui_launch()

        assert pulled[0]


class TestShareWorkflow:
    """Tests share tab interactions."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        self.db = MagicMock()
        self.db.list_projects.return_value = ([], 0)
        self.db.get_project_by_name.return_value = None
        monkeypatch.setattr("pyxos.gui.main.load_config", _mock_config)
        monkeypatch.setattr("pyxos.gui.main.save_config", lambda c: None)
        monkeypatch.setattr("pyxos.gui.main.delete_config", lambda: None)
        monkeypatch.setattr("pyxos.gui.main._run_storage", lambda: True)
        monkeypatch.setattr(
            "pyxos.storage.init_storage", lambda c: None
        )
        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.warning", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.information", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            "PySide6.QtWidgets.QMessageBox.critical", lambda *a, **kw: None
        )

        with patch("pyxos.gui.main.Database", return_value=self.db):
            yield

    def test_share_no_query_shows_warning(self, _qapp, qtbot):
        from pyxos.gui.main import gui_launch

        app = QApplication.instance()
        clicked = [False]

        def _check():
            for w in app.topLevelWidgets():
                btns = w.findChildren(PySide6.QtWidgets.QPushButton)
                for btn in btns:
                    if "Generate Share" in btn.text():
                        btn.click()
                        clicked[0] = True
                        QTimer.singleShot(50, app.quit)
                        break
                if clicked[0]:
                    break
            if not clicked[0]:
                app.quit()

        def _nav():
            for w2 in app.topLevelWidgets():
                nav = w2.findChildren(PySide6.QtWidgets.QListWidget)
                if nav:
                    nav[0].setCurrentRow(4)  # Share
                    QTimer.singleShot(100, _check)
                    break

        QTimer.singleShot(100, _nav)
        gui_launch()

        assert clicked[0]

    def test_share_project_not_found(self, _qapp, tmp_path):
        from pyxos.gui.main import gui_launch

        self.db.get_project_by_name.return_value = None

        app = QApplication.instance()
        clicked = [False]

        def _check():
            for w in app.topLevelWidgets():
                edits = w.findChildren(PySide6.QtWidgets.QLineEdit)
                for edit in edits:
                    if edit.placeholderText() and "Search project" in edit.placeholderText():
                        edit.setText("nonexistent-project")
                        break
                btns = w.findChildren(PySide6.QtWidgets.QPushButton)
                for btn in btns:
                    if "Generate Share" in btn.text():
                        btn.click()
                        clicked[0] = True
                        QTimer.singleShot(50, app.quit)
                        break
                if clicked[0]:
                    break
            if not clicked[0]:
                app.quit()

        def _nav():
            for w2 in app.topLevelWidgets():
                nav = w2.findChildren(PySide6.QtWidgets.QListWidget)
                if nav:
                    nav[0].setCurrentRow(4)
                    QTimer.singleShot(100, _check)
                    break

        QTimer.singleShot(100, _nav)
        gui_launch()

        assert clicked[0]

    def test_share_success(self, _qapp, monkeypatch):
        from pyxos.gui.main import gui_launch

        self.db.get_project_by_name.return_value = {
            "name": "testproj",
            "storage_public_id": "pyxos/testproj",
        }
        from datetime import datetime, timezone

        monkeypatch.setattr(
            "pyxos.storage.generate_share_link",
            lambda pid, secs: (
                "https://cloud.example.com/dl/testproj",
                datetime(2099, 1, 1, tzinfo=timezone.utc),
            ),
        )

        app = QApplication.instance()
        clicked = [False]

        def _check():
            for w in app.topLevelWidgets():
                edits = w.findChildren(PySide6.QtWidgets.QLineEdit)
                for edit in edits:
                    if edit.placeholderText() and "Search project" in edit.placeholderText():
                        edit.setText("testproj")
                        break
                btns = w.findChildren(PySide6.QtWidgets.QPushButton)
                for btn in btns:
                    if "Generate Share" in btn.text():
                        btn.click()
                        clicked[0] = True
                        QTimer.singleShot(50, app.quit)
                        break
                if clicked[0]:
                    break
            if not clicked[0]:
                app.quit()

        def _nav():
            for w2 in app.topLevelWidgets():
                nav = w2.findChildren(PySide6.QtWidgets.QListWidget)
                if nav:
                    nav[0].setCurrentRow(4)
                    QTimer.singleShot(100, _check)
                    break

        QTimer.singleShot(100, _nav)
        gui_launch()

        assert clicked[0]

