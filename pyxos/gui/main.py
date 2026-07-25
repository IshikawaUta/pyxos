import os
import webbrowser
from pathlib import Path

from pyxos.config import (
    load_config,
    save_config,
    delete_config,
)
from pyxos.database import Database


def _format_size(size):
    if size is None:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"

_STORAGE = None


def _get_storage():
    global _STORAGE
    if _STORAGE is None:
        from pyxos.storage import init_storage as _init

        cfg = load_config()
        _STORAGE = _init(cfg)
    return _STORAGE


def _run_storage():
    try:
        _get_storage()
    except RuntimeError:
        return None
    return True


def gui_launch():
    try:
        from PySide6.QtCore import QThread, Signal, Qt
        from PySide6.QtWidgets import (
            QApplication,
            QDialog,
            QFormLayout,
            QLineEdit,
            QPushButton,
            QVBoxLayout,
            QHBoxLayout,
            QLabel,
            QWidget,
            QListWidget,
            QListWidgetItem,
            QStackedWidget,
            QFrame,
            QTableWidget,
            QTableWidgetItem,
            QAbstractItemView,
            QMessageBox,
            QFileDialog,
            QRadioButton,
            QButtonGroup,
            QProgressBar,
            QCheckBox,
            QTextEdit,
        )
        from PySide6.QtGui import QPalette, QColor
    except ImportError:
        print(
            "PySide6 not installed. Run: pip install 'pyxos[gui]'"
        )
        return

    class Worker(QThread):
        finished = Signal(object)
        error = Signal(str)

        def __init__(self, fn, *args, **kwargs):
            super().__init__()
            self.fn = fn
            self.args = args
            self.kwargs = kwargs

        def run(self):
            try:
                result = self.fn(*self.args, **self.kwargs)
                self.finished.emit(result)
            except Exception as e:
                self.error.emit(str(e))

    class ConfigDialog(QDialog):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Pyxos — Configuration Required")
            self.setMinimumWidth(480)
            self._build_ui()

        def _build_ui(self):
            layout = QVBoxLayout(self)
            layout.setSpacing(12)

            title = QLabel("Welcome to Pyxos")
            title.setStyleSheet("font-size: 18px; font-weight: bold;")
            layout.addWidget(title)

            sub = QLabel(
                "Configure your storage backend and MongoDB connection."
            )
            sub.setWordWrap(True)
            layout.addWidget(sub)

            form = QFormLayout()
            form.setSpacing(8)

            self.storage_group = QButtonGroup(self)
            storage_row = QHBoxLayout()
            self.rb_cloudinary = QRadioButton("Cloudinary")
            self.rb_b2 = QRadioButton("B2")
            self.rb_cloudinary.setChecked(True)
            self.storage_group.addButton(self.rb_cloudinary)
            self.storage_group.addButton(self.rb_b2)
            storage_row.addWidget(self.rb_cloudinary)
            storage_row.addWidget(self.rb_b2)
            storage_row.addStretch()
            form.addRow("Storage:", storage_row)

            self.mongo_uri = QLineEdit()
            self.mongo_uri.setPlaceholderText("mongodb+srv://...")
            self.mongo_uri.setEchoMode(QLineEdit.EchoMode.Password)
            form.addRow("MongoDB URI:", self.mongo_uri)

            self.cloud_name = QLineEdit()
            self.cloud_name.setPlaceholderText("my-cloud")
            form.addRow("Cloud Name:", self.cloud_name)

            self.cloud_api_key = QLineEdit()
            self.cloud_api_key.setPlaceholderText("API Key")
            form.addRow("API Key:", self.cloud_api_key)

            self.cloud_api_secret = QLineEdit()
            self.cloud_api_secret.setPlaceholderText("API Secret")
            self.cloud_api_secret.setEchoMode(QLineEdit.EchoMode.Password)
            form.addRow("API Secret:", self.cloud_api_secret)

            self.b2_key_id = QLineEdit()
            self.b2_key_id.setPlaceholderText("Application Key ID")
            self.b2_key_id.hide()
            form.addRow("B2 Key ID:", self.b2_key_id)
            self.b2_key_id_label = form.itemAt(
                form.count() - 2
            ).widget()
            if self.b2_key_id_label:
                self.b2_key_id_label.hide()

            self.b2_key = QLineEdit()
            self.b2_key.setPlaceholderText("Application Key")
            self.b2_key.setEchoMode(QLineEdit.EchoMode.Password)
            self.b2_key.hide()
            form.addRow("B2 Key:", self.b2_key)
            self.b2_key_label = form.itemAt(form.count() - 2).widget()
            if self.b2_key_label:
                self.b2_key_label.hide()

            self.b2_bucket = QLineEdit()
            self.b2_bucket.setPlaceholderText("Bucket Name")
            self.b2_bucket.hide()
            form.addRow("B2 Bucket:", self.b2_bucket)
            self.b2_bucket_label = form.itemAt(
                form.count() - 2
            ).widget()
            if self.b2_bucket_label:
                self.b2_bucket_label.hide()

            layout.addLayout(form)

            def toggle_storage():
                is_cloud = self.rb_cloudinary.isChecked()
                self.cloud_name.setVisible(is_cloud)
                self.cloud_api_key.setVisible(is_cloud)
                self.cloud_api_secret.setVisible(is_cloud)
                if self.b2_key_id_label:
                    self.b2_key_id_label.setVisible(not is_cloud)
                if self.b2_key_label:
                    self.b2_key_label.setVisible(not is_cloud)
                if self.b2_bucket_label:
                    self.b2_bucket_label.setVisible(not is_cloud)
                self.b2_key_id.setVisible(not is_cloud)
                self.b2_key.setVisible(not is_cloud)
                self.b2_bucket.setVisible(not is_cloud)

            self.rb_cloudinary.toggled.connect(toggle_storage)

            btn_layout = QHBoxLayout()
            self.error_label = QLabel("")
            self.error_label.setStyleSheet("color: #f87171;")

            save_btn = QPushButton("Save & Connect")
            save_btn.clicked.connect(self._save)

            btn_layout.addWidget(self.error_label)
            btn_layout.addStretch()
            btn_layout.addWidget(save_btn)
            layout.addLayout(btn_layout)

        def _save(self):
            cfg = {}
            if self.rb_b2.isChecked():
                cfg["storage_type"] = "b2"
                cfg["b2_application_key_id"] = (
                    self.b2_key_id.text().strip()
                )
                cfg["b2_application_key"] = (
                    self.b2_key.text().strip()
                )
                cfg["b2_bucket_name"] = (
                    self.b2_bucket.text().strip()
                )
            else:
                cfg["storage_type"] = "cloudinary"
                cfg["cloudinary_cloud_name"] = (
                    self.cloud_name.text().strip()
                )
                cfg["cloudinary_api_key"] = (
                    self.cloud_api_key.text().strip()
                )
                cfg["cloudinary_api_secret"] = (
                    self.cloud_api_secret.text().strip()
                )
            cfg["mongodb_uri"] = self.mongo_uri.text().strip()

            if not cfg["mongodb_uri"]:
                self.error_label.setText("MongoDB URI is required.")
                return

            try:
                save_config(cfg)
                _get_storage()
                self.accept()
            except Exception as e:
                self.error_label.setText(str(e))

    class MainWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Pyxos — Project Manager")
            self.resize(1100, 700)
            self.setMinimumSize(900, 600)
            self._pages = {}
            self._db = None
            self._init_db()
            self._build_ui()

        def __del__(self):
            try:
                if hasattr(self, '_db') and self._db:
                    self._db.close()
            except Exception:
                pass

        def _init_db(self):
            cfg = load_config()
            uri = cfg.get("mongodb_uri", "")
            if uri:
                try:
                    self._db = Database(uri)
                except Exception:
                    self._db = None
            else:
                self._db = None

        def _build_ui(self):
            main_layout = QHBoxLayout(self)
            main_layout.setContentsMargins(0, 0, 0, 0)
            main_layout.setSpacing(0)

            # Sidebar
            sidebar = QFrame()
            sidebar.setFixedWidth(220)
            sidebar.setObjectName("sidebar")
            sidebar_layout = QVBoxLayout(sidebar)
            sidebar_layout.setContentsMargins(0, 0, 0, 0)
            sidebar_layout.setSpacing(0)

            brand = QLabel("  Pyxos")
            brand.setStyleSheet(
                "font-size: 16px; font-weight: bold; padding: 18px 16px;"
            )
            sidebar_layout.addWidget(brand)

            self.nav_list = QListWidget()
            self.nav_list.setFrameShape(QFrame.Shape.NoFrame)
            nav_items = [
                ("dashboard", "Dashboard"),
                ("projects", "Projects"),
                ("push", "Push"),
                ("pull", "Pull"),
                ("stats", "Statistics"),
            ]
            for key, label in nav_items:
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, key)
                self.nav_list.addItem(item)

            self.nav_list.currentRowChanged.connect(
                self._on_nav_changed
            )
            sidebar_layout.addWidget(self.nav_list)

            sidebar_layout.addStretch()

            config_btn = QPushButton(" Settings")
            config_btn.clicked.connect(self._show_config)
            sidebar_layout.addWidget(config_btn)

            main_layout.addWidget(sidebar)

            # Divider
            div = QFrame()
            div.setFrameShape(QFrame.Shape.VLine)
            div.setFixedWidth(1)
            main_layout.addWidget(div)

            # Content stack
            self.stack = QStackedWidget()
            self._pages["dashboard"] = self._create_dashboard()
            self._pages["projects"] = self._create_projects()
            self._pages["push"] = self._create_push()
            self._pages["pull"] = self._create_pull()
            self._pages["stats"] = self._create_stats()
            self._pages["config"] = self._create_config_page()

            for page in self._pages.values():
                self.stack.addWidget(page)

            main_layout.addWidget(self.stack, 1)

        def _on_nav_changed(self, index):
            item = self.nav_list.item(index)
            key = item.data(Qt.ItemDataRole.UserRole)
            self._navigate(key)

        def _navigate(self, key):
            if key in self._pages:
                self.stack.setCurrentWidget(self._pages[key])
            if key == "dashboard":
                self._load_dashboard()
            elif key == "projects":
                self._load_projects()
            elif key == "stats":
                self._load_stats()

        def _create_dashboard(self):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(24, 24, 24, 24)

            title = QLabel("Dashboard")
            title.setStyleSheet(
                "font-size: 20px; font-weight: bold;"
            )
            layout.addWidget(title)

            self.dash_stats = QLabel("Loading...")
            self.dash_stats.setStyleSheet("padding: 12px 0;")
            layout.addWidget(self.dash_stats)

            self.dash_table = QTableWidget()
            self.dash_table.setColumnCount(4)
            self.dash_table.setHorizontalHeaderLabels(
                ["Name", "Version", "Size", "Updated"]
            )
            self.dash_table.horizontalHeader().setStretchLastSection(
                True
            )
            self.dash_table.setEditTriggers(
                QAbstractItemView.EditTrigger.NoEditTriggers
            )
            self.dash_table.setSelectionBehavior(
                QAbstractItemView.SelectionBehavior.SelectRows
            )
            self.dash_table.doubleClicked.connect(
                self._open_project_detail
            )
            layout.addWidget(self.dash_table)
            return page

        def _load_dashboard(self):
            def _fetch():
                if not self._db:
                    return [], {
                        "total_projects": 0,
                        "total_size": 0,
                        "storage_backends": 0,
                    }
                try:
                    projects, total = self._db.list_projects(
                        page=1, per_page=10
                    )
                    stats = {
                        "total_projects": total,
                        "total_size": sum(
                            p.get("file_size", 0) for p in projects
                        ),
                        "storage_backends": len(
                            set(
                                p.get(
                                    "storage_type", "cloudinary"
                                )
                                for p in projects
                            )
                            if projects
                            else []
                        ),
                    }
                    self._db.close()
                    return projects, stats
                except Exception:
                    return [], {}

            self.worker = Worker(_fetch)
            self.worker.finished.connect(self._set_dashboard)
            self.worker.start()

        def _set_dashboard(self, data):
            projects, stats = data
            self.dash_stats.setText(
                f"Total: {stats.get('total_projects', 0)} projects  |  "
                f"Size: {_format_size(stats.get('total_size', 0))}  |  "
                f"Backends: {stats.get('storage_backends', 0)}"
            )
            self._populate_table(self.dash_table, projects)

        def _create_projects(self):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(24, 24, 24, 24)

            header = QHBoxLayout()
            title = QLabel("Projects")
            title.setStyleSheet(
                "font-size: 20px; font-weight: bold;"
            )
            header.addWidget(title)
            header.addStretch()

            self.project_search = QLineEdit()
            self.project_search.setPlaceholderText("Search...")
            self.project_search.setFixedWidth(200)
            self.project_search.textChanged.connect(
                self._load_projects
            )
            header.addWidget(self.project_search)
            layout.addLayout(header)

            self.project_table = QTableWidget()
            self.project_table.setColumnCount(5)
            self.project_table.setHorizontalHeaderLabels(
                ["Name", "Version", "Size", "Storage", "Updated"]
            )
            self.project_table.horizontalHeader().setStretchLastSection(
                True
            )
            self.project_table.setEditTriggers(
                QAbstractItemView.EditTrigger.NoEditTriggers
            )
            self.project_table.setSelectionBehavior(
                QAbstractItemView.SelectionBehavior.SelectRows
            )
            self.project_table.doubleClicked.connect(
                self._open_project_detail
            )
            layout.addWidget(self.project_table)

            footer = QHBoxLayout()
            self.project_page_label = QLabel("Page 1")
            footer.addWidget(self.project_page_label)
            footer.addStretch()
            prev_btn = QPushButton("Previous")
            prev_btn.clicked.connect(
                lambda: self._page_nav(-1)
            )
            next_btn = QPushButton("Next")
            next_btn.clicked.connect(lambda: self._page_nav(1))
            footer.addWidget(prev_btn)
            footer.addWidget(next_btn)
            layout.addLayout(footer)

            self._project_page = 1
            self._project_total_pages = 1
            return page

        def _page_nav(self, delta):
            new_page = self._project_page + delta
            if 1 <= new_page <= self._project_total_pages:
                self._project_page = new_page
                self._load_projects()

        def _load_projects(self):
            search = self.project_search.text().strip()

            def _fetch():
                if not self._db:
                    return [], 0, 1
                try:
                    projects, total = self._db.list_projects(
                        page=self._project_page,
                        per_page=20,
                        search=search if search else None,
                    )
                    self._db.close()
                    tp = max(1, (total + 19) // 20)
                    return projects, total, tp
                except Exception:
                    return [], 0, 1

            self.worker = Worker(_fetch)
            self.worker.finished.connect(self._set_projects)
            self.worker.start()

        def _set_projects(self, data):
            projects, total, tp = data
            self._project_total_pages = tp
            self.project_page_label.setText(
                f"Page {self._project_page} of {tp} ({total} projects)"
            )
            self._populate_table(self.project_table, projects)

        def _open_project_detail(self):
            table = self.sender() if self.sender() else self.dash_table
            if isinstance(self.sender(), QTableWidget):
                table = self.sender()
            else:
                return
            row = table.currentRow()
            if row < 0:
                return
            name_item = table.item(row, 0)
            if not name_item:
                return
            name = name_item.text()
            self._show_project_detail(name)

        def _show_project_detail(self, name):
            def _fetch():
                if not self._db:
                    return None
                try:
                    proj = self._db.get_project_by_name(name)
                    self._db.close()
                    return proj
                except Exception:
                    return None

            self.worker = Worker(_fetch)
            self.worker.finished.connect(self._detail_dialog)
            self.worker.start()

        def _detail_dialog(self, proj):
            if not proj:
                QMessageBox.warning(self, "Error", "Project not found.")
                return

            dlg = QDialog(self)
            dlg.setWindowTitle(f"{proj.get('name', '')} — Details")
            dlg.setMinimumWidth(500)
            layout = QVBoxLayout(dlg)

            info = QTextEdit()
            info.setReadOnly(True)
            lines = [
                f"<b>Name:</b> {proj.get('name', '-')}",
                f"<b>ID:</b> {proj.get('_id', '-')}",
                f"<b>Version:</b> {proj.get('version', '-')}",
                f"<b>Description:</b> {proj.get('description', '-')}",
                f"<b>Size:</b> {_format_size(proj.get('file_size', 0))}",
                f"<b>Files:</b> {proj.get('file_count', '-')}",
                f"<b>Storage:</b> {proj.get('storage_type', '-')}",
                f"<b>Encrypted:</b> {proj.get('encrypted', False)}",
                f"<b>Created:</b> {proj.get('created_at', '-')}",
                f"<b>Updated:</b> {proj.get('updated_at', '-')}",
            ]
            if proj.get("tags"):
                lines.append(
                    f"<b>Tags:</b> {', '.join(proj['tags'])}"
                )
            url = proj.get("storage_url") or proj.get(
                "cloudinary_url"
            )
            if url:
                lines.append(
                    f'<b>URL:</b> <a href="{url}">{url}</a>'
                )
            info.setHtml("<br>".join(lines))
            layout.addWidget(info)

            btn_layout = QHBoxLayout()
            delete_btn = QPushButton("Delete")
            delete_btn.clicked.connect(
                lambda: self._delete_project(proj, dlg)
            )
            btn_layout.addWidget(delete_btn)
            if url:
                open_btn = QPushButton("Open in Browser")
                open_btn.clicked.connect(
                    lambda: webbrowser.open(url)
                )
                btn_layout.addWidget(open_btn)
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(dlg.accept)
            btn_layout.addWidget(close_btn)
            layout.addLayout(btn_layout)
            dlg.exec()

        def _delete_project(self, proj, dlg):
            reply = QMessageBox.question(
                self,
                "Confirm Delete",
                f"Delete {proj.get('name', '')}? This cannot be undone.",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

            public_id = proj.get(
                "storage_public_id"
            ) or proj.get("cloudinary_public_id")

            def _do_delete():
                if public_id:
                    try:
                        from pyxos.storage import (
                            delete_project as cloud_delete,
                            init_storage,
                        )

                        cfg = load_config()
                        init_storage(cfg)
                        cloud_delete(public_id)
                    except Exception:
                        pass
                if self._db:
                    try:
                        self._db.delete_project(
                            project_id=proj["_id"]
                        )
                        self._db.close()
                    except Exception:
                        pass
                return True

            self.worker = Worker(_do_delete)
            self.worker.finished.connect(
                lambda _: self._on_deleted(dlg)
            )
            self.worker.start()

        def _on_deleted(self, dlg):
            dlg.accept()
            self._load_projects()
            self._load_dashboard()

        def _create_push(self):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(24, 24, 24, 24)

            title = QLabel("Push Project")
            title.setStyleSheet(
                "font-size: 20px; font-weight: bold;"
            )
            layout.addWidget(title)

            form = QFormLayout()
            form.setSpacing(10)

            path_row = QHBoxLayout()
            self.push_path = QLineEdit()
            self.push_path.setPlaceholderText("Select directory...")
            path_row.addWidget(self.push_path)
            browse_btn = QPushButton("Browse")
            browse_btn.clicked.connect(self._browse_push_path)
            path_row.addWidget(browse_btn)
            form.addRow("Project Path:", path_row)

            self.push_name = QLineEdit()
            form.addRow("Name:", self.push_name)

            self.push_desc = QLineEdit()
            form.addRow("Description:", self.push_desc)

            self.push_tags = QLineEdit()
            self.push_tags.setPlaceholderText("python, web, api")
            form.addRow("Tags:", self.push_tags)

            self.push_version = QLineEdit("1.0.0")
            form.addRow("Version:", self.push_version)

            self.push_encrypt = QCheckBox("Encrypt archive")
            form.addRow("", self.push_encrypt)

            self.push_force = QCheckBox("Overwrite if exists")
            form.addRow("", self.push_force)

            layout.addLayout(form)

            self.push_status = QLabel("")
            layout.addWidget(self.push_status)

            self.push_progress = QProgressBar()
            self.push_progress.setVisible(False)
            layout.addWidget(self.push_progress)

            push_btn = QPushButton(" Push to Cloud")
            push_btn.clicked.connect(self._do_push)
            layout.addWidget(push_btn)

            layout.addStretch()
            return page

        def _browse_push_path(self):
            path = QFileDialog.getExistingDirectory(
                self, "Select Project Directory"
            )
            if path:
                self.push_path.setText(path)

        def _do_push(self):
            path = self.push_path.text().strip()
            if not path:
                QMessageBox.warning(
                    self, "Error", "Select a project path."
                )
                return

            from pyxos.config import get_project_name, make_archive

            name = self.push_name.text().strip() or get_project_name(
                Path(path)
            )
            description = self.push_desc.text().strip()
            tags = [
                t.strip()
                for t in self.push_tags.text().split(",")
                if t.strip()
            ]
            version = self.push_version.text().strip() or "1.0.0"
            encrypt = self.push_encrypt.isChecked()
            force = self.push_force.isChecked()

            self.push_status.setText("Creating archive...")
            self.push_progress.setVisible(True)
            self.push_progress.setRange(0, 0)

            def _run():
                archive_path, file_count = make_archive(
                    Path(path), name
                )

                if encrypt:
                    from pyxos.crypto import encrypt_archive
                    import getpass as _gp

                    pw = _gp.getpass("Encryption password: ")
                    archive_path = encrypt_archive(
                        archive_path, pw
                    )

                from pyxos.storage import (
                    upload_project,
                    init_storage,
                )

                cfg = load_config()
                init_storage(cfg)

                url, public_id = upload_project(
                    archive_path, name
                )
                file_size = (
                    os.path.getsize(archive_path)
                    if os.path.exists(archive_path)
                    else 0
                )

                if self._db:
                    try:
                        self._db.create_project(
                            name=name,
                            description=description,
                            tags=tags,
                            version=version,
                            storage_url=url,
                            storage_public_id=public_id,
                            local_path=str(Path(path).resolve()),
                            file_size=file_size,
                            file_count=file_count,
                            encrypted=encrypt,
                            force=force,
                        )
                        self._db.close()
                    except Exception as e:
                        return {"error": str(e)}

                try:
                    os.unlink(archive_path)
                except OSError:
                    pass

                return {"success": True, "url": url}

            self.worker = Worker(_run)
            self.worker.finished.connect(self._on_push_done)
            self.worker.error.connect(self._on_push_error)
            self.worker.start()

        def _on_push_done(self, result):
            self.push_progress.setVisible(False)
            if isinstance(result, dict):
                if result.get("error"):
                    self.push_status.setText(
                        f"Error: {result['error']}"
                    )
                else:
                    self.push_status.setText(
                        f"Pushed! {result.get('url', '')}"
                    )
                    self.push_name.clear()
                    self.push_desc.clear()
                    self.push_tags.clear()

        def _on_push_error(self, err):
            self.push_progress.setVisible(False)
            self.push_status.setText(f"Error: {err}")

        def _create_pull(self):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(24, 24, 24, 24)

            title = QLabel("Pull Project")
            title.setStyleSheet(
                "font-size: 20px; font-weight: bold;"
            )
            layout.addWidget(title)

            form = QFormLayout()
            form.setSpacing(10)

            self.pull_search = QLineEdit()
            self.pull_search.setPlaceholderText(
                "Project name or ID..."
            )
            form.addRow("Search:", self.pull_search)

            output_row = QHBoxLayout()
            self.pull_output = QLineEdit()
            self.pull_output.setPlaceholderText(
                "Output directory (default: current)"
            )
            output_row.addWidget(self.pull_output)
            browse_btn = QPushButton("Browse")
            browse_btn.clicked.connect(self._browse_pull_output)
            output_row.addWidget(browse_btn)
            form.addRow("Output:", output_row)

            self.pull_decrypt = QCheckBox("Decrypt after download")
            form.addRow("", self.pull_decrypt)

            layout.addLayout(form)

            self.pull_status = QLabel("")
            layout.addWidget(self.pull_status)

            self.pull_progress = QProgressBar()
            self.pull_progress.setVisible(False)
            layout.addWidget(self.pull_progress)

            pull_btn = QPushButton(" Pull from Cloud")
            pull_btn.clicked.connect(self._do_pull)
            layout.addWidget(pull_btn)

            layout.addStretch()
            return page

        def _browse_pull_output(self):
            path = QFileDialog.getExistingDirectory(
                self, "Select Output Directory"
            )
            if path:
                self.pull_output.setText(path)

        def _do_pull(self):
            query = self.pull_search.text().strip()
            if not query:
                QMessageBox.warning(
                    self,
                    "Error",
                    "Enter a project name or ID to pull.",
                )
                return

            output = self.pull_output.text().strip() or "."
            decrypt = self.pull_decrypt.isChecked()

            self.pull_status.setText("Downloading...")
            self.pull_progress.setVisible(True)
            self.pull_progress.setRange(0, 0)

            def _run():
                if not self._db:
                    return {"error": "Database not connected."}
                proj = self._db.get_project_by_name(query)
                if not proj:
                    try:
                        from bson import ObjectId

                        proj = self._db.get_project_by_id(
                            ObjectId(query)
                        )
                    except Exception:
                        pass
                self._db.close()
                if not proj:
                    return {"error": f"Project '{query}' not found."}

                from pyxos.storage import (
                    download_project,
                    init_storage,
                )

                cfg = load_config()
                init_storage(cfg)
                public_id = proj.get(
                    "storage_public_id"
                ) or proj.get("cloudinary_public_id")
                dest = Path(output)
                archive = download_project(public_id, dest)

                import shutil
                import zipfile

                extract_dir = dest / proj.get("name", "project")
                with zipfile.ZipFile(archive, "r") as zf:
                    zf.extractall(extract_dir)

                if decrypt:
                    from pyxos.crypto import (
                        decrypt_archive,
                    )

                    dec_path = decrypt_archive(
                        str(archive), proj.get("name", "proj")
                    )
                    try:
                        shutil.rmtree(extract_dir)
                    except OSError:
                        pass
                    extract_dir = Path(dec_path).parent / Path(
                        dec_path
                    ).stem
                    import zipfile as zf2

                    with zf2.ZipFile(dec_path, "r") as zf:
                        zf.extractall(extract_dir)

                try:
                    os.unlink(archive)
                except OSError:
                    pass

                return {
                    "success": True,
                    "path": str(extract_dir),
                }

            self.worker = Worker(_run)
            self.worker.finished.connect(self._on_pull_done)
            self.worker.error.connect(self._on_pull_error)
            self.worker.start()

        def _on_pull_done(self, result):
            self.pull_progress.setVisible(False)
            if isinstance(result, dict):
                if result.get("error"):
                    self.pull_status.setText(
                        f"Error: {result['error']}"
                    )
                else:
                    self.pull_status.setText(
                        f"Downloaded to: {result.get('path', '')}"
                    )

        def _on_pull_error(self, err):
            self.pull_progress.setVisible(False)
            self.pull_status.setText(f"Error: {err}")

        def _create_stats(self):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(24, 24, 24, 24)

            title = QLabel("Statistics")
            title.setStyleSheet(
                "font-size: 20px; font-weight: bold;"
            )
            layout.addWidget(title)

            self.stats_label = QLabel("Loading...")
            layout.addWidget(self.stats_label)

            self.stats_table = QTableWidget()
            self.stats_table.setColumnCount(2)
            self.stats_table.setHorizontalHeaderLabels(
                ["Metric", "Value"]
            )
            self.stats_table.horizontalHeader().setStretchLastSection(
                True
            )
            self.stats_table.setEditTriggers(
                QAbstractItemView.EditTrigger.NoEditTriggers
            )
            layout.addWidget(self.stats_table)

            layout.addStretch()
            return page

        def _load_stats(self):
            def _fetch():
                if not self._db:
                    return {}
                try:
                    projects, total = self._db.list_projects(
                        page=1, per_page=1000
                    )
                    self._db.close()
                    storage_types = {}
                    for p in projects:
                        st = p.get("storage_type", "cloudinary")
                        storage_types[st] = (
                            storage_types.get(st, 0) + 1
                        )
                    total_tags = len(
                        set(
                            tag
                            for p in projects
                            for tag in p.get("tags", [])
                        )
                    )
                    return {
                        "total": total,
                        "size": sum(
                            p.get("file_size", 0)
                            for p in projects
                        ),
                        "backends": len(storage_types),
                        "tags": total_tags,
                        "storage_breakdown": storage_types,
                    }
                except Exception:
                    return {}

            self.worker = Worker(_fetch)
            self.worker.finished.connect(self._set_stats)
            self.worker.start()

        def _set_stats(self, data):
            if not data:
                self.stats_label.setText("No data.")
                return
            self.stats_label.setText(
                f"{data['total']} projects  |  "
                f"{_format_size(data['size'])}  |  "
                f"{data['backends']} backends  |  "
                f"{data['tags']} unique tags"
            )
            self.stats_table.setRowCount(0)
            for st, count in data.get(
                "storage_breakdown", {}
            ).items():
                row = self.stats_table.rowCount()
                self.stats_table.insertRow(row)
                self.stats_table.setItem(
                    row, 0, QTableWidgetItem(st)
                )
                self.stats_table.setItem(
                    row,
                    1,
                    QTableWidgetItem(str(count)),
                )

        def _create_config_page(self):
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(24, 24, 24, 24)

            title = QLabel("Configuration")
            title.setStyleSheet(
                "font-size: 20px; font-weight: bold;"
            )
            layout.addWidget(title)

            self.config_text = QTextEdit()
            self.config_text.setReadOnly(True)
            layout.addWidget(self.config_text)

            btn_layout = QHBoxLayout()
            reset_btn = QPushButton("Reset Config")
            reset_btn.clicked.connect(self._reset_config)
            btn_layout.addWidget(reset_btn)
            btn_layout.addStretch()
            layout.addLayout(btn_layout)

            layout.addStretch()
            return page

        def _show_config(self):
            self._navigate("config")
            self._refresh_config()

        def _refresh_config(self):
            cfg = load_config()
            lines = []
            blacklist = {
                "cloudinary_api_secret",
                "b2_application_key",
                "mongodb_uri",
            }
            for k, v in cfg.items():
                if k in blacklist and v:
                    lines.append(
                        f"<b>{k}:</b> {'*' * min(len(v), 16)}"
                    )
                else:
                    lines.append(f"<b>{k}:</b> {v}")
            self.config_text.setHtml("<br>".join(lines))

        def _reset_config(self):
            reply = QMessageBox.question(
                self,
                "Confirm Reset",
                "Delete all Pyxos configuration?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            delete_config()
            self._db = None
            self._refresh_config()
            QMessageBox.information(
                self, "Done", "Configuration deleted."
            )

        def _populate_table(self, table, projects):
            table.setRowCount(0)
            for p in projects:
                row = table.rowCount()
                table.insertRow(row)
                table.setItem(
                    row, 0, QTableWidgetItem(p.get("name", ""))
                )
                table.setItem(
                    row,
                    1,
                    QTableWidgetItem(p.get("version", "-")),
                )
                table.setItem(
                    row,
                    2,
                    QTableWidgetItem(
                        _format_size(p.get("file_size", 0))
                    ),
                )
                storage_col = 3
                if table.columnCount() == 4:
                    storage_col = -1
                if storage_col >= 0:
                    table.setItem(
                        row,
                        storage_col,
                        QTableWidgetItem(
                            p.get("storage_type", "-")
                        ),
                    )
                updated = p.get("updated_at")
                if hasattr(updated, "strftime"):
                    updated = updated.strftime(
                        "%Y-%m-%d %H:%M"
                    )
                else:
                    updated = str(updated) if updated else "-"
                last_col = table.columnCount() - 1
                table.setItem(
                    row, last_col, QTableWidgetItem(updated)
                )
            table.resizeColumnsToContents()

    # Force XCB on Wayland to avoid crashes
    if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = "xcb"

    app = QApplication([])
    app.setApplicationName("Pyxos")
    app.setStyle("Fusion")

    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(22, 22, 28))
    pal.setColor(
        QPalette.ColorRole.WindowText, QColor(235, 235, 245)
    )
    pal.setColor(QPalette.ColorRole.Base, QColor(28, 28, 34))
    pal.setColor(
        QPalette.ColorRole.AlternateBase, QColor(32, 32, 40)
    )
    pal.setColor(QPalette.ColorRole.Text, QColor(235, 235, 245))
    pal.setColor(
        QPalette.ColorRole.Button, QColor(38, 38, 48)
    )
    pal.setColor(
        QPalette.ColorRole.ButtonText, QColor(235, 235, 245)
    )
    pal.setColor(
        QPalette.ColorRole.Highlight, QColor(108, 99, 255)
    )
    pal.setColor(
        QPalette.ColorRole.HighlightedText, QColor(255, 255, 255)
    )
    app.setPalette(pal)

    app.setStyleSheet("""
        QListWidget {
            background: #16161c;
            border: none;
            font-size: 14px;
            padding: 4px;
        }
        QListWidget::item {
            padding: 10px 16px;
            border-radius: 6px;
            margin: 2px 4px;
        }
        QListWidget::item:selected {
            background: rgba(108, 99, 255, 0.2);
            color: #a78bfa;
        }
        QListWidget::item:hover:!selected {
            background: rgba(255, 255, 255, 0.04);
        }
        QTableWidget {
            background: #1c1c22;
            alternate-background-color: #22222a;
            border: 1px solid #2a2a34;
            gridline-color: #2a2a34;
            border-radius: 6px;
            font-size: 13px;
        }
        QTableWidget::item {
            padding: 6px;
        }
        QTableWidget::item:selected {
            background: rgba(108, 99, 255, 0.3);
        }
        QHeaderView::section {
            background: #22222a;
            padding: 8px;
            border: none;
            border-bottom: 1px solid #2a2a34;
            font-weight: bold;
            font-size: 12px;
            text-transform: uppercase;
            color: #888;
        }
        QLineEdit, QComboBox, QSpinBox, QTextEdit {
            background: #1c1c22;
            border: 1px solid #2a2a34;
            border-radius: 6px;
            padding: 8px;
            color: #ebebf5;
            font-size: 13px;
        }
        QLineEdit:focus, QComboBox:focus, QTextEdit:focus {
            border-color: #6c63ff;
        }
        QPushButton {
            background: #6c63ff;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            color: white;
            font-weight: bold;
            font-size: 13px;
        }
        QPushButton:hover {
            background: #5a52e0;
        }
        QPushButton:pressed {
            background: #4a42c0;
        }
        QPushButton:disabled {
            background: #333;
            color: #666;
        }
        QRadioButton, QCheckBox {
            color: #ebebf5;
            font-size: 13px;
        }
        QProgressBar {
            border: 1px solid #2a2a34;
            border-radius: 4px;
            text-align: center;
            background: #1c1c22;
            height: 20px;
        }
        QProgressBar::chunk {
            background: #6c63ff;
            border-radius: 3px;
        }
        QLabel {
            color: #ebebf5;
        }
        QFrame#sidebar {
            background: #16161c;
        }
        QGroupBox {
            border: 1px solid #2a2a34;
            border-radius: 6px;
            margin-top: 12px;
            padding-top: 12px;
            color: #ebebf5;
            font-weight: bold;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 6px;
        }
    """)

    cfg = load_config()
    if not cfg.get("mongodb_uri") or (
        cfg.get("storage_type") == "cloudinary"
        and not cfg.get("cloudinary_api_secret")
    ):
        dlg = ConfigDialog()
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
    else:
        try:
            _run_storage()
        except RuntimeError:
            pass

    win = MainWindow()
    win.show()
    win._navigate("dashboard")
    app.exec()