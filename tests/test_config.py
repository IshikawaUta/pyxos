import json
import zipfile
from pathlib import Path

from pyxos import config


class TestConfigLoadSave:
    def test_load_config_from_file(self, sample_config):
        result = config.load_config()
        assert result["mongodb_uri"] == sample_config["mongodb_uri"]

    def test_load_config_no_file(self, tmp_path, monkeypatch):
        old = config.CONFIG_FILE
        try:
            config.CONFIG_FILE = Path("/nonexistent/config.json")
            for k in ("PYXOS_MONGODB_URI", "PYXOS_CLOUDINARY_CLOUD_NAME",
                      "PYXOS_CLOUDINARY_API_KEY", "PYXOS_CLOUDINARY_API_SECRET"):
                monkeypatch.setenv(k, "")
            monkeypatch.chdir(tmp_path)
            result = config.load_config()
            assert result == {}
        finally:
            config.CONFIG_FILE = old

    def test_load_config_from_dotenv(self, tmp_path, monkeypatch):
        old = config.CONFIG_FILE
        try:
            config.CONFIG_FILE = Path("/nonexistent/config.json")
            for k in ("PYXOS_MONGODB_URI", "PYXOS_CLOUDINARY_CLOUD_NAME",
                      "PYXOS_CLOUDINARY_API_KEY", "PYXOS_CLOUDINARY_API_SECRET"):
                monkeypatch.setenv(k, "")
            env = tmp_path / ".env"
            env.write_text('mongodb_uri=mongodb://env\ncloudinary_cloud_name=envcloud')
            monkeypatch.chdir(tmp_path)
            result = config.load_config()
            assert result["mongodb_uri"] == "mongodb://env"
        finally:
            config.CONFIG_FILE = old

    def test_load_config_dotenv_quotes(self, tmp_path, monkeypatch):
        old = config.CONFIG_FILE
        try:
            config.CONFIG_FILE = Path("/nonexistent/config.json")
            for k in ("PYXOS_MONGODB_URI", "PYXOS_CLOUDINARY_CLOUD_NAME",
                      "PYXOS_CLOUDINARY_API_KEY", "PYXOS_CLOUDINARY_API_SECRET"):
                monkeypatch.setenv(k, "")
            env = tmp_path / ".env"
            env.write_text("mongodb_uri='mongodb://quoted'\ncloudinary_cloud_name=\"qcloud\"")
            monkeypatch.chdir(tmp_path)
            result = config.load_config()
            assert result["mongodb_uri"] == "mongodb://quoted"
        finally:
            config.CONFIG_FILE = old

    def test_load_config_env_override(self, sample_config, monkeypatch):
        monkeypatch.setenv("PYXOS_MONGODB_URI", "mongodb://override")
        result = config.load_config()
        assert result["mongodb_uri"] == "mongodb://override"

    def test_load_config_dotenv_skip_comments(self, tmp_path, monkeypatch):
        old = config.CONFIG_FILE
        try:
            config.CONFIG_FILE = Path("/nonexistent/config.json")
            for k in ("PYXOS_MONGODB_URI", "PYXOS_CLOUDINARY_CLOUD_NAME",
                      "PYXOS_CLOUDINARY_API_KEY", "PYXOS_CLOUDINARY_API_SECRET"):
                monkeypatch.setenv(k, "")
            env = tmp_path / ".env"
            env.write_text("# comment\nmongodb_uri=mongodb://real\n# another")
            monkeypatch.chdir(tmp_path)
            result = config.load_config()
            assert result["mongodb_uri"] == "mongodb://real"
        finally:
            config.CONFIG_FILE = old

    def test_save_and_delete_config(self, config_file):
        data = {"mongodb_uri": "mongodb://test", "cloudinary_cloud_name": "c"}
        config.save_config(data)
        assert config_file.exists()
        loaded = json.loads(config_file.read_text())
        assert loaded == data
        assert config.delete_config() is True
        assert not config_file.exists()
        assert config.delete_config() is False

    def test_ensure_config_dir(self, config_file):
        config.ensure_config_dir()
        assert config_file.parent.exists()


class TestExcludePatterns:
    def test_default(self, tmp_path):
        p, _i = config.build_exclude_patterns(tmp_path)
        assert ".git" in p

    def test_pyxosignore(self, tmp_path):
        (tmp_path / ".pyxosignore").write_text("*.log\n# comment\n*.tmp")
        p, _ = config.build_exclude_patterns(tmp_path)
        assert "*.log" in p

    def test_extra_excludes(self, tmp_path):
        p, _ = config.build_exclude_patterns(tmp_path, extra_excludes=["*.md"])
        assert "*.md" in p

    def test_no_duplicates(self, tmp_path):
        p, _ = config.build_exclude_patterns(tmp_path, extra_excludes=[".git"])
        assert p.count(".git") == 1

    def test_extra_includes(self, tmp_path):
        _, i = config.build_exclude_patterns(tmp_path, extra_includes=["main.py"])
        assert i == ["main.py"]

    def test_should_exclude_match(self):
        assert config.should_exclude("x.pyc", ["*.pyc"]) is True

    def test_should_exclude_no_match(self):
        assert config.should_exclude("x.py", ["*.pyc"]) is False

    def test_should_exclude_include_overrides(self):
        assert config.should_exclude("main.py", ["*.py"], includes=["main.py"]) is False

    def test_should_exclude_include_no_override(self):
        assert config.should_exclude("other.py", ["*.py"], includes=["main.py"]) is True

    def test_path_parts_excluded(self):
        assert config._path_parts_excluded(".git/HEAD", [".git"]) is True
        assert config._path_parts_excluded("src/main.py", [".git"]) is False

    def test_path_parts_excluded_with_includes(self):
        assert config._path_parts_excluded(".git/HEAD", [".git"], includes=[".git"]) is False


class TestArchiveFunctions:
    def test_get_project_name(self, tmp_path):
        p = tmp_path / "myapp"
        p.mkdir()
        assert config.get_project_name(p) == "myapp"

    def test_count_archive_files(self, temp_project):
        c, _ = config.count_archive_files(temp_project)
        assert c >= 3

    def test_get_archive_file_list(self, temp_project):
        files, _ = config.get_archive_file_list(temp_project)
        names = [f[0] for f in files]
        assert "main.py" in names
        assert ".git/HEAD" not in names

    def test_get_archive_file_list_extra_excludes(self, temp_project):
        files, _ = config.get_archive_file_list(temp_project, extra_excludes=["*.md"])
        names = [f[0] for f in files]
        assert "main.py" in names
        assert "README.md" not in names

    def test_get_archive_file_list_with_includes(self, temp_project):
        files, _ = config.get_archive_file_list(temp_project, extra_excludes=["*.py"], extra_includes=["main.py"])
        names = [f[0] for f in files]
        assert "main.py" in names
        assert "utils.py" not in names
        assert "README.md" in names

    def test_make_archive(self, temp_project, tmp_path):
        out = tmp_path / "a.zip"
        res = config.make_archive(temp_project, out)
        assert res.exists()
        with zipfile.ZipFile(res) as z:
            assert "main.py" in z.namelist()

    def test_make_archive_with_extra_excludes(self, temp_project, tmp_path):
        out = tmp_path / "a2.zip"
        res = config.make_archive(temp_project, out, extra_excludes=["*.md"])
        with zipfile.ZipFile(res) as z:
            assert "main.py" in z.namelist()
            assert "README.md" not in z.namelist()

    def test_get_archive_file_list_skips_symlinks(self, temp_project):
        link = temp_project / "mylink"
        link.symlink_to(temp_project / "main.py")
        files, _ = config.get_archive_file_list(temp_project)
        names = [f[0] for f in files]
        assert "mylink" not in names
        assert "main.py" in names


class TestGlobPatternMatching:
    def test_simple_wildcard(self):
        assert config._match_pattern("file.pyc", "*.pyc") is True
        assert config._match_pattern("file.py", "*.pyc") is False

    def test_path_specific(self):
        assert config._match_pattern("src/file.pyc", "src/*.pyc") is True
        assert config._match_pattern("other/file.pyc", "src/*.pyc") is False
        assert config._match_pattern("src/subdir/file.pyc", "src/*.pyc") is False

    def test_double_star(self):
        assert config._match_pattern("any/file.pyc", "**/*.pyc") is True
        assert config._match_pattern("a/b/c/file.pyc", "**/*.pyc") is True
        assert config._match_pattern("file.pyc", "**/*.pyc") is True

    def test_double_star_prefix(self):
        assert config._match_pattern("src/sub/nested", "src/**/nested") is True
        assert config._match_pattern("src/nested", "src/**/nested") is True
        assert config._match_pattern("other/nested", "src/**/nested") is False

    def test_name_only(self):
        assert config._match_pattern("path/to/__pycache__/file.pyc", "__pycache__") is True
        assert config._match_pattern("random.txt", "__pycache__") is False

    def test_empty_pattern(self):
        assert config._match_pattern("anything", "") is False

    def test_should_exclude_simple(self):
        assert config.should_exclude("file.pyc", ["*.pyc"]) is True
        assert config.should_exclude("file.txt", ["*.pyc"]) is False

    def test_should_exclude_include_override(self):
        assert config.should_exclude(".git/HEAD", [".git"], includes=[".git"]) is False
        assert config.should_exclude(".git/HEAD", [".git"], includes=["secret*"]) is True

    def test_path_parts_complex(self):
        assert config._path_parts_excluded("src/__pycache__/file.pyc", ["*.pyc", "__pycache__"]) is True
        assert config._path_parts_excluded("src/other/file.txt", ["*.pyc"]) is False
        assert config._path_parts_excluded("src/file.pyc", ["src/*.pyc"]) is True
        assert config._path_parts_excluded("deep/nested/file.pyc", ["**/*.pyc"]) is True

    def test_question_mark(self):
        assert config._match_pattern("file.pyc", "file.?yc") is True
        assert config._match_pattern("file.py", "file.?yc") is False
        assert config._match_pattern("src/file.pyc", "src/file.?yc") is True
        assert config._match_pattern("notsrc/file.pyc", "src/file.?yc") is False

    def test_character_class(self):
        assert config._match_pattern("file.pyc", "file.[pP]yc") is True
        assert config._match_pattern("file.Pyc", "file.[pP]yc") is True
        assert config._match_pattern("file.Ryc", "file.[pP]yc") is False
        assert config._match_pattern("a/file.pyc", "**/file.[pP]yc") is True

    def test_special_regex_chars(self):
        assert config._match_pattern("test+file.txt", "test+file.txt") is True
        assert config._match_pattern("test.file.txt", "test.file.txt") is True
        assert config._match_pattern("src/test+file.txt", "src/test+file.*") is True
