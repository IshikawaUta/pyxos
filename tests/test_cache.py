import json
import time
from datetime import datetime, timezone

import pytest
from bson import ObjectId

from pyxos import cache


class TestCache:
    @pytest.fixture(autouse=True)
    def setup_cache(self, tmp_path, monkeypatch):
        """Point cache to temp directory."""
        cache_dir = tmp_path / ".pyxos"
        cache_dir.mkdir()
        cache_file = cache_dir / "cache.json"
        monkeypatch.setattr("pyxos.cache.CACHE_DIR", cache_dir)
        monkeypatch.setattr("pyxos.cache.CACHE_FILE", cache_file)
        yield

    def test_save_and_load(self):
        projects = [{"name": "test", "version": "1.0.0"}]
        cache.save_cache(projects)
        
        loaded = cache.load_cache()
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0]["name"] == "test"

    def test_load_expired(self, monkeypatch):
        projects = [{"name": "old"}]
        cache.save_cache(projects)
        
        # Manipulate cache timestamp to be old
        cache_file = cache.CACHE_DIR / "cache.json"
        data = json.loads(cache_file.read_text())
        data["cached_at"] = time.time() - 7200  # 2 hours ago
        cache_file.write_text(json.dumps(data))
        
        # Should be expired with default 1h max age
        loaded = cache.load_cache(max_age_seconds=3600)
        assert loaded is None

    def test_load_no_cache_file(self, tmp_path, monkeypatch):
        # Use directory with no cache file
        empty_dir = tmp_path / "nocache"
        empty_dir.mkdir()
        monkeypatch.setattr("pyxos.cache.CACHE_DIR", empty_dir)
        monkeypatch.setattr("pyxos.cache.CACHE_FILE", empty_dir / "cache.json")
        
        loaded = cache.load_cache()
        assert loaded is None

    def test_invalidate(self):
        projects = [{"name": "x"}]
        cache.save_cache(projects)
        assert cache.load_cache() is not None
        
        cache.invalidate_cache()
        assert cache.load_cache() is None

    def test_save_empty_list(self):
        cache.save_cache([])
        loaded = cache.load_cache()
        assert loaded == []

    def test_load_cache_with_large_max_age(self):
        projects = [{"name": "fresh"}]
        cache.save_cache(projects)
        
        loaded = cache.load_cache(max_age_seconds=999999)
        assert loaded is not None

    def test_load_cache_corrupted_json(self, monkeypatch, tmp_path):
        cache_dir = tmp_path / ".pyxos_corrupt"
        cache_dir.mkdir()
        cache_file = cache_dir / "cache.json"
        cache_file.write_text("{invalid json")
        monkeypatch.setattr("pyxos.cache.CACHE_DIR", cache_dir)
        monkeypatch.setattr("pyxos.cache.CACHE_FILE", cache_file)
        
        loaded = cache.load_cache()
        assert loaded is None

    def test_invalidate_no_file(self, monkeypatch, tmp_path):
        empty_dir = tmp_path / ".pyxos_empty"
        empty_dir.mkdir()
        monkeypatch.setattr("pyxos.cache.CACHE_DIR", empty_dir)
        monkeypatch.setattr("pyxos.cache.CACHE_FILE", empty_dir / "cache.json")
        
        result = cache.invalidate_cache()
        assert result is False

    def test_save_cache_non_serializable(self, monkeypatch, tmp_path):
        """Test save_cache raises TypeError for non-serializable types."""
        cache_dir = tmp_path / ".pyxos_err"
        cache_dir.mkdir()
        monkeypatch.setattr("pyxos.cache.CACHE_DIR", cache_dir)
        monkeypatch.setattr("pyxos.cache.CACHE_FILE", cache_dir / "cache.json")
        
        class Unserializable:
            pass
        
        projects = [{"data": Unserializable()}]
        with pytest.raises(TypeError, match="not serializable"):
            cache.save_cache(projects)

    def test_save_cache_with_objectid_and_datetime(self, monkeypatch, tmp_path):
        cache_dir = tmp_path / ".pyxos_serializer"
        cache_dir.mkdir()
        monkeypatch.setattr("pyxos.cache.CACHE_DIR", cache_dir)
        monkeypatch.setattr("pyxos.cache.CACHE_FILE", cache_dir / "cache.json")

        projects = [{
            "_id": ObjectId(),
            "name": "test",
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        }]
        cache.save_cache(projects)

        loaded = cache.load_cache(max_age_seconds=9999)
        assert loaded is not None
        assert loaded[0]["name"] == "test"
        assert isinstance(loaded[0]["_id"], str)
