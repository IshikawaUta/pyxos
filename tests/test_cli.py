import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import click
import pytest
from click.testing import CliRunner
from bson import ObjectId

from pyxos.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_project_doc():
    oid = ObjectId()
    return {
        "_id": oid,
        "name": "testproj",
        "description": "A test project",
        "tags": ["python", "cli"],
        "version": "1.0.0",
        "storage_url": "https://cloud.example.com/pyxos/testproj.zip",
        "storage_public_id": "pyxos/testproj",
        "local_path": "/home/user/testproj",
        "file_size": 1024000,
        "file_count": 42,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
    }


def _make_fake_archive(project_path, output_path, *args, **kwargs):
    """Creates a real zip file so archive_path.stat() succeeds."""
    archive = Path(str(output_path.with_suffix("")) + ".zip")
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("main.py", "print('hello')")
    return archive


@pytest.fixture
def mock_dependencies(sample_project_doc, tmp_path):
    """Mock Database, cloudinary, and config, with make_archive creating real files."""
    with patch("pyxos.cli.Database") as MockDB, \
         patch("pyxos.cli.cloud_upload") as mock_up, \
         patch("pyxos.cli.cloud_delete") as mock_del, \
         patch("pyxos.cli.cloud_download") as mock_down, \
         patch("pyxos.cli.ping_storage") as mock_ping, \
         patch("pyxos.cli.init_storage") as mock_init_s, \
         patch("pyxos.cli.load_config") as mock_cfg, \
         patch("pyxos.cli.save_config") as mock_save, \
         patch("pyxos.cli.delete_config") as mock_delcfg, \
         patch("pyxos.cli.make_archive", side_effect=_make_fake_archive) as mock_make, \
         patch("pyxos.cli.count_archive_files") as mock_count, \
         patch("pyxos.cli.get_archive_file_list") as mock_list, \
         patch("pyxos.cli.build_exclude_patterns") as mock_pats, \
         patch("pyxos.cli.get_project_name") as mock_name:

        default_cfg = {
            "mongodb_uri": "mongodb://fake",
            "cloudinary_cloud_name": "mycloud",
            "cloudinary_api_key": "apikey123",
            "cloudinary_api_secret": "secret",
        }
        mock_cfg.return_value = default_cfg

        mock_db = MagicMock()
        MockDB.return_value = mock_db
        mock_db.check_connection.return_value = True
        mock_db.get_project.return_value = None
        mock_db.list_projects.return_value = ([sample_project_doc], 1)
        mock_db.create_project.return_value = str(ObjectId())
        mock_db.update_project.return_value = 1
        mock_db.delete_project.return_value = 1

        mock_up.return_value = ("https://cloud.example.com/pyxos/testproj.zip", "pyxos/testproj")
        mock_ping.return_value = True
        mock_count.return_value = (10, 50000)
        mock_list.return_value = ([("main.py", 1000), ("utils.py", 2000)], 3000)
        mock_pats.return_value = ([".git", "__pycache__"], [])
        mock_name.return_value = "testproj"

        real_zip = tmp_path / "dl" / "pyxos_testproj.zip"
        real_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(real_zip, "w") as zf:
            zf.writestr("main.py", "print('hello')")
        mock_down.return_value = real_zip

        yield {
            "db": mock_db,
            "upload": mock_up,
            "delete": mock_del,
            "download": mock_down,
            "ping": mock_ping,
            "init_s": mock_init_s,
            "load_config": mock_cfg,
            "count_files": mock_count,
            "file_list": mock_list,
            "build_pats": mock_pats,
            "get_name": mock_name,
        }


class TestInitCommand:
    def test_init_success(self, runner, mock_dependencies):
        r = runner.invoke(main, [
            "init", "--storage-type", "cloudinary",
            "--mongodb-uri", "m://t",
            "--cloudinary-cloud-name", "c",
            "--cloudinary-api-key", "k",
            "--cloudinary-api-secret", "s",
        ])
        assert r.exit_code == 0
        assert "Configuration saved" in r.output

    def test_init_mongo_fails(self, runner, mock_dependencies):
        mock_dependencies["db"].check_connection.return_value = False
        r = runner.invoke(main, [
            "init", "--storage-type", "cloudinary",
            "--mongodb-uri", "m://b",
            "--cloudinary-cloud-name", "c",
            "--cloudinary-api-key", "k", "--cloudinary-api-secret", "s",
        ])
        assert r.exit_code == 0
        assert "Could not connect to MongoDB" in r.output

    def test_init_cloudinary_fails(self, runner, mock_dependencies):
        mock_dependencies["ping"].return_value = False
        r = runner.invoke(main, [
            "init", "--storage-type", "cloudinary",
            "--mongodb-uri", "m://t",
            "--cloudinary-cloud-name", "c",
            "--cloudinary-api-key", "k", "--cloudinary-api-secret", "s",
        ])
        assert r.exit_code == 0
        assert "Could not connect to" in r.output


class TestPushCommand:
    def test_dry_run(self, runner, mock_dependencies, tmp_path):
        r = runner.invoke(main, ["push", str(tmp_path), "--dry-run"])
        assert r.exit_code == 0
        assert "Dry run" in r.output

    def test_dry_run_with_excludes(self, runner, mock_dependencies, tmp_path):
        r = runner.invoke(main, ["push", str(tmp_path), "--dry-run", "-e", "*.log", "-i", "e.log"])
        assert r.exit_code == 0

    def test_dry_run_more_than_30_files(self, runner, mock_dependencies, tmp_path):
        many = [(f"file_{i}.py", 100) for i in range(35)]
        mock_dependencies["file_list"].return_value = (many, sum(s for _, s in many))
        r = runner.invoke(main, ["push", str(tmp_path), "--dry-run"])
        assert r.exit_code == 0
        assert "and 5 more files" in r.output

    def test_requires_cloudinary(self, runner, mock_dependencies, tmp_path):
        mock_dependencies["load_config"].return_value = {"mongodb_uri": "m://t"}
        r = runner.invoke(main, ["push", str(tmp_path)])
        assert r.exit_code == 1

    def test_already_exists_no_force(self, runner, mock_dependencies, tmp_path):
        mock_dependencies["db"].get_project.return_value = {
            "_id": ObjectId(), "name": "testproj", "version": "1.0", "description": "old"
        }
        r = runner.invoke(main, ["push", str(tmp_path)])
        assert r.exit_code == 0
        assert "already exists" in r.output

    def test_force_overwrite(self, runner, mock_dependencies, tmp_path):
        existing = {"_id": ObjectId(), "name": "testproj"}
        mock_dependencies["db"].get_project.return_value = existing
        r = runner.invoke(main, ["push", str(tmp_path), "--force"])
        assert r.exit_code == 0
        assert "pushed successfully" in r.output

    def test_success(self, runner, mock_dependencies, tmp_path):
        r = runner.invoke(main, ["push", str(tmp_path), "-n", "a", "-d", "d", "-t", "a,b", "-v", "2.0"])
        assert r.exit_code == 0
        assert "pushed successfully" in r.output

    def test_size_warning_accepted(self, runner, mock_dependencies, tmp_path):
        mock_dependencies["count_files"].return_value = (10, 100 * 1024 * 1024)
        r = runner.invoke(main, ["push", str(tmp_path)], input="y\n")
        assert r.exit_code == 0

    def test_size_warning_declined(self, runner, mock_dependencies, tmp_path):
        mock_dependencies["count_files"].return_value = (10, 100 * 1024 * 1024)
        r = runner.invoke(main, ["push", str(tmp_path)], input="n\n")
        assert r.exit_code == 0
        assert "Cancelled" in r.output

    def test_no_confirm_size(self, runner, mock_dependencies, tmp_path):
        mock_dependencies["count_files"].return_value = (10, 100 * 1024 * 1024)
        r = runner.invoke(main, ["push", str(tmp_path), "--no-confirm-size"])
        assert r.exit_code == 0
        assert "pushed successfully" in r.output

    def test_too_large(self, runner, mock_dependencies, tmp_path):
        mock_dependencies["upload"].side_effect = ValueError("Archive size (11.0 MB) exceeds Cloudinary free tier limit")
        r = runner.invoke(main, ["push", str(tmp_path), "-n", "a"])
        assert r.exit_code == 0
        assert "exceeds Cloudinary" in r.output

    def test_cloudinary_upload_error(self, runner, mock_dependencies, tmp_path):
        import cloudinary.exceptions
        mock_dependencies["upload"].side_effect = cloudinary.exceptions.Error("auth failed")
        r = runner.invoke(main, ["push", str(tmp_path), "-n", "a"])
        assert r.exit_code == 0
        assert "Storage error" in r.output


class TestPullCommand:
    def test_by_name(self, runner, mock_dependencies, sample_project_doc, tmp_path):
        mock_dependencies["db"].get_project.return_value = sample_project_doc
        r = runner.invoke(main, ["pull", "testproj", "-o", str(tmp_path)])
        assert r.exit_code == 0
        assert "pulled" in r.output

    def test_not_found(self, runner, mock_dependencies):
        mock_dependencies["db"].get_project.return_value = None
        r = runner.invoke(main, ["pull", "nonexistent"])
        assert r.exit_code == 0
        assert "not found" in r.output

    def test_no_public_id(self, runner, mock_dependencies):
        mock_dependencies["db"].get_project.return_value = {
            "_id": ObjectId(), "name": "b", "storage_public_id": None
        }
        r = runner.invoke(main, ["pull", "b"])
        assert r.exit_code == 0
        assert "No storage public_id" in r.output

    def test_public_id_fallback_old_field(self, runner, mock_dependencies, sample_project_doc):
        doc = {**sample_project_doc, "storage_public_id": None, "cloudinary_public_id": "pyxos/legacy"}
        mock_dependencies["db"].get_project.return_value = doc
        r = runner.invoke(main, ["pull", "testproj", "--force"])
        assert r.exit_code == 0
        assert "pulled" in r.output

    def test_interactive_empty(self, runner, mock_dependencies):
        mock_dependencies["db"].list_projects.return_value = ([], 0)
        r = runner.invoke(main, ["pull"])
        assert r.exit_code == 0
        assert "No projects found" in r.output

    def test_interactive_select(self, runner, mock_dependencies, sample_project_doc, tmp_path):
        mock_dependencies["db"].list_projects.return_value = ([sample_project_doc], 1)
        out = tmp_path / "o"
        out.mkdir()
        r = runner.invoke(main, ["pull", "-o", str(out)], input="1\n")
        assert r.exit_code == 0
        assert "pulled" in r.output

    def test_existing_dir_no_force(self, runner, mock_dependencies, sample_project_doc, tmp_path):
        mock_dependencies["db"].get_project.return_value = sample_project_doc
        d = tmp_path / "testproj"
        d.mkdir()
        r = runner.invoke(main, ["pull", "testproj", "-o", str(tmp_path)])
        assert r.exit_code == 0
        assert "already exists" in r.output

    def test_force(self, runner, mock_dependencies, sample_project_doc, tmp_path):
        mock_dependencies["db"].get_project.return_value = sample_project_doc
        d = tmp_path / "testproj"
        d.mkdir()
        r = runner.invoke(main, ["pull", "testproj", "-o", str(tmp_path), "--force"])
        assert r.exit_code == 0
        assert "pulled" in r.output


class TestUpdateCommand:
    def test_metadata(self, runner, mock_dependencies, sample_project_doc):
        mock_dependencies["db"].get_project.return_value = sample_project_doc
        r = runner.invoke(main, ["update", "testproj", "-d", "new", "-v", "2.0"])
        assert r.exit_code == 0
        assert "updated" in r.output

    def test_update_tags(self, runner, mock_dependencies, sample_project_doc):
        mock_dependencies["db"].get_project.return_value = sample_project_doc
        r = runner.invoke(main, ["update", "testproj", "-t", "py,web"])
        assert r.exit_code == 0
        assert "updated" in r.output

    def test_rename(self, runner, mock_dependencies, sample_project_doc):
        mock_dependencies["db"].get_project.side_effect = [sample_project_doc, None]
        r = runner.invoke(main, ["update", "testproj", "-n", "newname"])
        assert r.exit_code == 0

    def test_rename_conflict(self, runner, mock_dependencies, sample_project_doc):
        conflict = dict(sample_project_doc)
        conflict["_id"] = ObjectId()
        mock_dependencies["db"].get_project.side_effect = [sample_project_doc, conflict]
        r = runner.invoke(main, ["update", "testproj", "-n", "newname"])
        assert r.exit_code == 0
        assert "already taken" in r.output

    def test_reupload_no_local_path(self, runner, mock_dependencies):
        mock_dependencies["db"].get_project.return_value = {
            "_id": ObjectId(), "name": "t", "local_path": None
        }
        r = runner.invoke(main, ["update", "t", "--reupload"])
        assert r.exit_code == 0
        assert "Local path not available" in r.output

    def test_reupload(self, runner, mock_dependencies, sample_project_doc, tmp_path):
        doc = dict(sample_project_doc)
        doc["local_path"] = str(tmp_path)
        mock_dependencies["db"].get_project.return_value = doc
        r = runner.invoke(main, ["update", "testproj", "--reupload", "-v", "2.0"])
        assert r.exit_code == 0
        assert "Re-uploaded" in r.output

    def test_no_options(self, runner, mock_dependencies, sample_project_doc):
        mock_dependencies["db"].get_project.return_value = sample_project_doc
        r = runner.invoke(main, ["update", "testproj"])
        assert r.exit_code == 0
        assert "No options provided" in r.output

    def test_not_found(self, runner, mock_dependencies):
        mock_dependencies["db"].get_project.return_value = None
        r = runner.invoke(main, ["update", "x", "-d", "x"])
        assert r.exit_code == 0
        assert "not found" in r.output


class TestInfoCommand:
    def test_by_name(self, runner, mock_dependencies, sample_project_doc):
        mock_dependencies["db"].get_project.return_value = sample_project_doc
        r = runner.invoke(main, ["info", "testproj"])
        assert r.exit_code == 0
        assert "Project Details" in r.output

    def test_not_found(self, runner, mock_dependencies):
        mock_dependencies["db"].get_project.return_value = None
        r = runner.invoke(main, ["info", "x"])
        assert r.exit_code == 0
        assert "not found" in r.output

    def test_interactive(self, runner, mock_dependencies, sample_project_doc):
        mock_dependencies["db"].list_projects.return_value = ([sample_project_doc], 1)
        r = runner.invoke(main, ["info"], input="1\n")
        assert r.exit_code == 0
        assert "Project Details" in r.output

    def test_interactive_empty(self, runner, mock_dependencies):
        mock_dependencies["db"].list_projects.return_value = ([], 0)
        r = runner.invoke(main, ["info"])
        assert r.exit_code == 0
        assert "No projects found" in r.output


class TestListCommand:
    def test_basic(self, runner, mock_dependencies, sample_project_doc):
        mock_dependencies["db"].list_projects.return_value = ([sample_project_doc], 1)
        r = runner.invoke(main, ["list"])
        assert r.exit_code == 0
        assert "testproj" in r.output

    def test_empty(self, runner, mock_dependencies):
        mock_dependencies["db"].list_projects.return_value = ([], 0)
        r = runner.invoke(main, ["list"])
        assert r.exit_code == 0
        assert "No projects found" in r.output

    def test_json(self, runner, mock_dependencies, sample_project_doc):
        mock_dependencies["db"].list_projects.return_value = ([sample_project_doc], 1)
        r = runner.invoke(main, ["list", "--json"])
        assert r.exit_code == 0
        # skip logo lines, extract JSON portion
        output = r.output
        json_start = output.index("{")
        assert json.loads(output[json_start:])["total"] == 1

    def test_search(self, runner, mock_dependencies):
        mock_dependencies["db"].list_projects.return_value = ([], 0)
        r = runner.invoke(main, ["list", "-s", "kw"])
        assert r.exit_code == 0

    def test_tags(self, runner, mock_dependencies):
        mock_dependencies["db"].list_projects.return_value = ([], 0)
        r = runner.invoke(main, ["list", "-t", "py", "-t", "web"])
        assert r.exit_code == 0

    def test_pagination_hint(self, runner, mock_dependencies, sample_project_doc):
        mock_dependencies["db"].list_projects.return_value = ([sample_project_doc], 50)
        r = runner.invoke(main, ["list"])
        assert r.exit_code == 0
        assert "Next page" in r.output

    def test_requires_mongodb(self, runner, mock_dependencies):
        mock_dependencies["load_config"].return_value = {}
        r = runner.invoke(main, ["list"])
        assert r.exit_code == 1


class TestDeleteCommand:
    def test_by_name(self, runner, mock_dependencies, sample_project_doc):
        mock_dependencies["db"].get_project.return_value = sample_project_doc
        r = runner.invoke(main, ["delete", "testproj"], input="y\n")
        assert r.exit_code == 0
        assert "deleted" in r.output

    def test_cancelled(self, runner, mock_dependencies, sample_project_doc):
        mock_dependencies["db"].get_project.return_value = sample_project_doc
        r = runner.invoke(main, ["delete", "testproj"], input="n\n")
        assert r.exit_code == 0
        assert "Cancelled" in r.output

    def test_yes_flag(self, runner, mock_dependencies, sample_project_doc):
        mock_dependencies["db"].get_project.return_value = sample_project_doc
        r = runner.invoke(main, ["delete", "testproj", "--yes"])
        assert r.exit_code == 0
        assert "deleted" in r.output

    def test_not_found(self, runner, mock_dependencies):
        mock_dependencies["db"].get_project.return_value = None
        r = runner.invoke(main, ["delete", "x", "--yes"])
        assert r.exit_code == 0
        assert "not found" in r.output

    def test_all_requires_yes(self, runner, mock_dependencies):
        r = runner.invoke(main, ["delete", "--all"])
        assert r.exit_code == 0
        assert "requires --yes" in r.output

    def test_all(self, runner, mock_dependencies, sample_project_doc):
        mock_dependencies["db"].list_projects.return_value = ([sample_project_doc], 1)
        r = runner.invoke(main, ["delete", "--all", "--yes"])
        assert r.exit_code == 0
        assert "Deleted" in r.output

    def test_all_empty(self, runner, mock_dependencies):
        mock_dependencies["db"].list_projects.return_value = ([], 0)
        r = runner.invoke(main, ["delete", "--all", "--yes"])
        assert r.exit_code == 0
        assert "No projects to delete" in r.output

    def test_cloudinary_error(self, runner, mock_dependencies, sample_project_doc):
        mock_dependencies["db"].get_project.return_value = sample_project_doc
        mock_dependencies["delete"].side_effect = RuntimeError("fail")
        r = runner.invoke(main, ["delete", "testproj", "--yes"])
        assert r.exit_code == 0
        assert "Storage" in r.output

    def test_interactive(self, runner, mock_dependencies, sample_project_doc):
        mock_dependencies["db"].list_projects.return_value = ([sample_project_doc], 1)
        r = runner.invoke(main, ["delete"], input="1\ny\n")
        assert r.exit_code == 0
        assert "deleted" in r.output


class TestOpenCommand:
    def test_by_name(self, runner, mock_dependencies, sample_project_doc):
        mock_dependencies["db"].get_project.return_value = sample_project_doc
        with patch("pyxos.cli.webbrowser.open"):
            r = runner.invoke(main, ["open", "testproj"])
        assert r.exit_code == 0
        assert "Opened" in r.output

    def test_no_url(self, runner, mock_dependencies):
        mock_dependencies["db"].get_project.return_value = {
            "_id": ObjectId(), "name": "n", "storage_url": None
        }
        r = runner.invoke(main, ["open", "n"])
        assert r.exit_code == 0
        assert "No storage URL" in r.output

    def test_not_found(self, runner, mock_dependencies):
        mock_dependencies["db"].get_project.return_value = None
        r = runner.invoke(main, ["open", "x"])
        assert r.exit_code == 0
        assert "not found" in r.output


class TestCheckCommand:
    def test_all_connected(self, runner, mock_dependencies):
        r = runner.invoke(main, ["check"])
        assert r.exit_code == 0
        assert "MongoDB Atlas: Connected" in r.output
        assert "CLOUDINARY: Connected" in r.output

    def test_mongo_fail(self, runner, mock_dependencies):
        mock_dependencies["db"].check_connection.return_value = False
        r = runner.invoke(main, ["check"])
        assert r.exit_code == 0
        assert "Connection failed" in r.output

    def test_no_mongo_uri(self, runner, mock_dependencies):
        mock_dependencies["load_config"].return_value = {
            "cloudinary_cloud_name": "c", "cloudinary_api_key": "k", "cloudinary_api_secret": "s",
        }
        r = runner.invoke(main, ["check"])
        assert r.exit_code == 0
        assert "Not configured" in r.output

    def test_cloudinary_not_configured(self, runner, mock_dependencies):
        mock_dependencies["load_config"].return_value = {"mongodb_uri": "m://t"}
        mock_dependencies["init_s"].side_effect = ValueError("Missing config")
        r = runner.invoke(main, ["check"])
        assert r.exit_code == 0
        assert "Not fully configured" in r.output

    def test_cloudinary_fail(self, runner, mock_dependencies):
        mock_dependencies["ping"].return_value = False
        r = runner.invoke(main, ["check"])
        assert r.exit_code == 0
        assert "Connection failed" in r.output


class TestConfigCommand:
    def test_show(self, runner, mock_dependencies):
        r = runner.invoke(main, ["config", "show"])
        assert r.exit_code == 0
        assert "mycloud" in r.output

    def test_show_partial(self, runner, mock_dependencies):
        mock_dependencies["load_config"].return_value = {"mongodb_uri": "m://x"}
        r = runner.invoke(main, ["config", "show"])
        assert r.exit_code == 0
        assert "(not set)" in r.output

    def test_reset_confirmed(self, runner, mock_dependencies):
        r = runner.invoke(main, ["config", "reset"], input="y\n")
        assert r.exit_code == 0
        assert "deleted" in r.output

    def test_reset_cancelled(self, runner, mock_dependencies):
        r = runner.invoke(main, ["config", "reset"], input="n\n")
        assert r.exit_code == 0
        assert "Cancelled" in r.output

    def test_reset_yes(self, runner, mock_dependencies):
        r = runner.invoke(main, ["config", "reset", "--yes"])
        assert r.exit_code == 0
        assert "deleted" in r.output

    def test_reset_no_file(self, runner, mock_dependencies):
        from pyxos.cli import delete_config as dc
        with patch("pyxos.cli.delete_config", return_value=False):
            r = runner.invoke(main, ["config", "reset", "--yes"])
        assert r.exit_code == 0
        assert "No configuration found" in r.output


class TestHelperFunctions:
    def test_resolve_by_id(self, mock_dependencies, sample_project_doc):
        from pyxos.cli import _resolve_project
        mock_dependencies["db"].get_project.return_value = sample_project_doc
        assert _resolve_project(mock_dependencies["db"], str(sample_project_doc["_id"])) == sample_project_doc

    def test_resolve_by_name(self, mock_dependencies, sample_project_doc):
        from pyxos.cli import _resolve_project
        mock_dependencies["db"].get_project.side_effect = [None, sample_project_doc]
        assert _resolve_project(mock_dependencies["db"], "testproj") == sample_project_doc

    def test_format_size(self):
        from pyxos.cli import _format_size
        assert _format_size(0) == "-"
        assert _format_size(500) == "0.5 KB"
        assert _format_size(5 * 1024 * 1024) == "5.0 MB"

    def test_error_handler_abort(self):
        from pyxos.cli import _error_handler
        with pytest.raises(SystemExit) as e:
            _error_handler(click.Abort, click.Abort(), None)
        assert e.value.code == 0

    def test_error_handler_usage(self):
        from pyxos.cli import _error_handler
        with pytest.raises(SystemExit) as e:
            _error_handler(click.exceptions.UsageError, click.exceptions.UsageError("bad"), None)
        assert e.value.code == 1

    def test_error_handler_keyboard(self):
        from pyxos.cli import _error_handler
        with pytest.raises(SystemExit) as e:
            _error_handler(KeyboardInterrupt, KeyboardInterrupt(), None)
        assert e.value.code == 0

    def test_error_handler_generic(self):
        from pyxos.cli import _error_handler
        with pytest.raises(SystemExit) as e:
            _error_handler(Exception, Exception("oops"), None)
        assert e.value.code == 1

    def test_get_db_no_config(self, mock_dependencies):
        from pyxos.cli import get_db
        mock_dependencies["load_config"].return_value = {}
        with pytest.raises(SystemExit):
            get_db()

    def test_require_storage_missing(self):
        from pyxos.cli import require_storage
        with pytest.raises(SystemExit):
            require_storage({})


class TestSelectProject:
    def test_empty(self, mock_dependencies):
        from pyxos.cli import _select_project
        mock_dependencies["db"].list_projects.return_value = ([], 0)
        assert _select_project(mock_dependencies["db"]) is None

    def test_invalid_choice(self, mock_dependencies, sample_project_doc):
        from pyxos.cli import _select_project
        mock_dependencies["db"].list_projects.return_value = ([sample_project_doc], 1)
        with patch("click.prompt", side_effect=ValueError()):
            assert _select_project(mock_dependencies["db"]) is None

    def test_out_of_range(self, mock_dependencies, sample_project_doc):
        from pyxos.cli import _select_project
        mock_dependencies["db"].list_projects.return_value = ([sample_project_doc], 1)
        with patch("click.prompt", return_value=99):
            assert _select_project(mock_dependencies["db"]) is None

    def test_abort(self, mock_dependencies, sample_project_doc):
        from pyxos.cli import _select_project
        mock_dependencies["db"].list_projects.return_value = ([sample_project_doc], 1)
        with patch("click.prompt", side_effect=click.Abort()):
            assert _select_project(mock_dependencies["db"]) is None
