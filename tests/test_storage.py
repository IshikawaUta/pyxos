from unittest.mock import MagicMock, patch

import cloudinary
import pytest

from pyxos import storage


class TestUploadProject:
    def test_upload_project(self, tmp_path, mock_cloudinary):
        archive = tmp_path / "test.zip"
        archive.write_bytes(b"dummy data")
        url, pid = storage.upload_project(archive, "myproject")
        assert url == "https://cloudinary.com/fake.zip"
        assert pid == "pyxos/testproj"

    def test_upload_too_large(self, tmp_path, mock_cloudinary):
        archive = tmp_path / "big.zip"
        archive.write_bytes(b"x" * (storage.CLOUDINARY_MAX_SIZE + 1))
        with pytest.raises(ValueError, match="exceeds Cloudinary free tier limit"):
            storage.upload_project(archive, "myproject")

    def test_upload_within_limit(self, tmp_path, mock_cloudinary):
        archive = tmp_path / "ok.zip"
        archive.write_bytes(b"x" * (storage.CLOUDINARY_MAX_SIZE - 100))
        url, _pid = storage.upload_project(archive, "myproject")
        assert url == "https://cloudinary.com/fake.zip"


class TestDeleteProject:
    def test_success(self, mock_cloudinary):
        assert storage.delete_project("pyxos/t") is True
        mock_cloudinary["destroy"].assert_called_once_with("pyxos/t", resource_type="raw")

    def test_error(self):
        with patch("cloudinary.uploader.destroy", side_effect=cloudinary.exceptions.Error("fail")):
            with pytest.raises(RuntimeError, match="Cloudinary error"):
                storage.delete_project("pyxos/t")


class TestDownloadProject:
    def test_download(self, tmp_path, mock_cloudinary):
        dest = tmp_path / "dl"
        dest.mkdir()

        with patch("pyxos.storage.cloudinary_url", return_value=("https://fake/x.zip", None)):
            with patch("urllib.request.build_opener") as mbo:
                resp = MagicMock()
                resp.status = 200
                resp.headers = {"Content-Length": "20"}
                resp.read.side_effect = [b"fake zip content", b""]
                mock_opener = MagicMock()
                mock_opener.open.return_value = resp
                mbo.return_value = mock_opener

                result = storage.download_project("pyxos/t", dest)

        assert result.exists()
        assert result.name == "pyxos_t.zip"
        assert result.read_bytes() == b"fake zip content"

    def test_download_no_content_length(self, tmp_path, mock_cloudinary):
        dest = tmp_path / "dl"
        dest.mkdir()

        with patch("pyxos.storage.cloudinary_url", return_value=("https://fake/x.zip", None)):
            with patch("urllib.request.build_opener") as mbo:
                resp = MagicMock()
                resp.status = 200
                resp.headers = {}
                resp.read.side_effect = [b"data", b""]
                mock_opener = MagicMock()
                mock_opener.open.return_value = resp
                mbo.return_value = mock_opener

                result = storage.download_project("pyxos/t", dest)

        assert result.exists()

    def test_download_error(self, tmp_path, mock_cloudinary):
        dest = tmp_path / "dl"
        dest.mkdir()

        with patch("pyxos.storage.cloudinary_url", return_value=("https://fake/x.zip", None)):
            resp = MagicMock()
            resp.status = 200
            resp.headers = {"Content-Length": "500"}
            resp.read.side_effect = OSError("Network down")
            mock_opener = MagicMock()
            mock_opener.open.return_value = resp
            with patch("urllib.request.build_opener", return_value=mock_opener):
                with pytest.raises(RuntimeError, match="Download failed"):
                    storage.download_project("pyxos/t", dest)
            archive_path = dest / "pyxos_t.zip"
            assert not archive_path.exists()


class TestPingCloudinary:
    def test_ping_success(self, mock_cloudinary):
        assert storage.ping_storage() is True

    def test_ping_failure(self):
        with patch("cloudinary.api.ping", side_effect=cloudinary.exceptions.Error("down")):
            assert storage.ping_storage() is False


class TestB2Storage:
    @pytest.fixture(autouse=True)
    def _setup_b2(self):
        b2_cfg = {
            "storage_type": "b2",
            "b2_application_key_id": "kid",
            "b2_application_key": "secret",
            "b2_bucket_name": "my-bucket",
        }
        with patch("b2sdk.v2.InMemoryAccountInfo"), \
             patch("b2sdk.v2.B2Api") as MockApi:
            mock_api = MagicMock()
            mock_bucket = MagicMock()
            MockApi.return_value = mock_api
            mock_api.get_bucket_by_name.return_value = mock_bucket
            mock_bucket.get_download_url.return_value = "https://b2.example.com/file.zip"
            mock_bucket.ls.return_value = iter([MagicMock()])

            storage.init_storage(b2_cfg)
            self.bucket = mock_bucket
            yield
        storage._state = {}
        storage._b2_bucket = None

    def test_init_storage_b2(self):
        assert storage._storage_type() == "b2"
        assert storage._b2_bucket is not None

    def test_init_storage_b2_missing_keys(self):
        with pytest.raises(ValueError, match="Missing B2 config"):
            storage.init_storage({"storage_type": "b2"})

    def test_init_storage_unknown_type(self):
        with pytest.raises(ValueError, match="Unknown storage type"):
            storage.init_storage({"storage_type": "s3", "b2_application_key_id": "k", "b2_application_key": "s", "b2_bucket_name": "b"})

    def test_b2_upload(self, tmp_path):
        archive = tmp_path / "test.zip"
        archive.write_bytes(b"b2 test data")
        url, pid = storage.upload_project(archive, "myproject")
        assert url == "https://b2.example.com/file.zip"
        assert pid == "pyxos/myproject.zip"
        self.bucket.upload.assert_called_once()

    def test_b2_delete(self):
        mock_file = MagicMock()
        mock_file.id_ = "v4_abc"
        mock_file.file_name = "pyxos/myproject.zip"
        self.bucket.list_file_versions.return_value = [mock_file]

        result = storage.delete_project("pyxos/myproject.zip")
        assert result is True
        self.bucket.delete_file_version.assert_called_once_with("v4_abc", "pyxos/myproject.zip")

    def test_b2_delete_error(self):
        from b2sdk.v2.exception import B2Error
        self.bucket.list_file_versions.side_effect = B2Error("gone")
        with pytest.raises(RuntimeError, match="B2 error"):
            storage.delete_project("pyxos/myproject.zip")

    def test_b2_download_no_zip_suffix(self, tmp_path):
        """B2 download where public_id doesn't end with .zip."""
        self.bucket.get_download_authorization.return_value = "fake-token"
        self.bucket.get_download_url.return_value = "https://b2.example.com/fake"

        with patch("urllib.request.build_opener") as mbo:
            resp = MagicMock()
            resp.status = 200
            resp.headers = {"Content-Length": "7"}
            resp.read.side_effect = [b"content", b""]
            mock_opener = MagicMock()
            mock_opener.open.return_value = resp
            mbo.return_value = mock_opener

            dest = tmp_path / "dl"
            result = storage.download_project("pyxos/myproject", dest)
            assert result.exists()
            assert result.read_bytes() == b"content"

    def test_b2_download(self, tmp_path):
        self.bucket.get_download_authorization.return_value = "fake-token"
        self.bucket.get_download_url.return_value = "https://b2.example.com/fake"

        with patch("urllib.request.build_opener") as mbo:
            resp = MagicMock()
            resp.status = 200
            resp.headers = {"Content-Length": "10"}
            resp.read.side_effect = [b"b2_content", b""]
            mock_opener = MagicMock()
            mock_opener.open.return_value = resp
            mbo.return_value = mock_opener

            dest = tmp_path / "dl"
            result = storage.download_project("pyxos/myproject.zip", dest)
            assert result.exists()
            assert result.read_bytes() == b"b2_content"

    def test_b2_ping(self):
        assert storage.ping_storage() is True

    def test_b2_ping_failure(self):
        from b2sdk.v2.exception import B2Error
        self.bucket.ls.side_effect = B2Error("auth")
        assert storage.ping_storage() is False

    def test_b2_upload_error(self, tmp_path):
        from b2sdk.v2.exception import B2Error
        archive = tmp_path / "test.zip"
        archive.write_bytes(b"test data")
        self.bucket.upload.side_effect = B2Error("permission denied")
        with pytest.raises(B2Error):
            storage.upload_project(archive, "testproj")


class TestShareLink:
    def test_cloudinary_share_link(self, mock_cloudinary):
        storage.init_storage({
            "storage_type": "cloudinary",
            "cloudinary_cloud_name": "mycloud",
            "cloudinary_api_key": "12345",
            "cloudinary_api_secret": "secret",
        })
        with patch("pyxos.storage.cloudinary_url") as mu:
            mu.return_value = ("https://res.cloudinary.com/mycloud/raw/upload/v123/signed_url", None)
            url, _ = storage.generate_share_link("pyxos/testproj", 3600)
            assert "cloudinary" in url or url.startswith("https://")


class TestResumeDownload:
    def test_resume_new_download(self, tmp_path, mock_cloudinary):
        """Test download without existing partial file."""
        with patch("pyxos.storage.cloudinary_url", return_value=("https://fake/x.zip", None)):
            with patch("urllib.request.build_opener") as mbo:
                resp = MagicMock()
                resp.status = 200
                resp.headers = {"Content-Length": "20"}
                resp.read.side_effect = [b"fake content", b""]
                mock_opener = MagicMock()
                mock_opener.open.return_value = resp
                mbo.return_value = mock_opener

                dest = tmp_path / "dl"
                dest.mkdir()
                result = storage.download_project("pyxos/test", dest)

                assert result.exists()
                assert not (dest / "pyxos_test.zip.part").exists()  # part file cleaned

    def test_resume_existing_partial(self, tmp_path, mock_cloudinary):
        """Test resuming download from partial file."""
        dest = tmp_path / "dl"
        dest.mkdir()
        part = dest / "pyxos_test.zip.part"
        part.write_bytes(b"half")

        with patch("pyxos.storage.cloudinary_url", return_value=("https://fake/x.zip", None)):
            with patch("urllib.request.build_opener") as mbo:
                resp = MagicMock()
                resp.status = 206
                resp.headers = {"Content-Range": "bytes 4-19/20", "Content-Length": "16"}
                resp.read.side_effect = [b"complete data", b""]
                mock_opener = MagicMock()
                mock_opener.open.return_value = resp
                mbo.return_value = mock_opener

                result = storage.download_project("pyxos/test", dest)
                assert result.exists()


class TestStorageInit:
    def test_init_b2_missing_optional(self):
        """B2 init should work without b2-specific fields if storage_type not b2."""
        config = {"storage_type": "b2", "b2_application_key_id": "k", "b2_application_key": "s", "b2_bucket_name": "b"}
        with patch("b2sdk.v2.InMemoryAccountInfo"), \
             patch("b2sdk.v2.B2Api") as MockApi:
            mock_api = MagicMock()
            mock_bucket = MagicMock()
            MockApi.return_value = mock_api
            mock_api.get_bucket_by_name.return_value = mock_bucket
            mock_bucket.get_download_url.return_value = "https://b2.example.com/file.zip"
            storage.init_storage(config)
        assert storage._storage_type() == "b2"
        assert storage._b2_bucket is not None
        storage._state = {}
        storage._b2_bucket = None

    def test_init_unknown_type(self):
        with pytest.raises(ValueError, match="Unknown storage type"):
            storage.init_storage({"storage_type": "s3"})


class TestPingStorage:
    def test_ping_storage_b2(self):
        config = {"storage_type": "b2", "b2_application_key_id": "k", "b2_application_key": "s", "b2_bucket_name": "b"}
        with patch("b2sdk.v2.InMemoryAccountInfo"), \
             patch("b2sdk.v2.B2Api") as MockApi:
            mock_api = MagicMock()
            mock_bucket = MagicMock()
            MockApi.return_value = mock_api
            mock_api.get_bucket_by_name.return_value = mock_bucket
            mock_bucket.get_download_url.return_value = "https://b2.example.com/file.zip"
            mock_bucket.ls.return_value = iter([MagicMock()])
            storage.init_storage(config)
            result = storage.ping_storage()
            assert result is True
        storage._state = {}
        storage._b2_bucket = None


class TestGenerateB2ShareLink:
    def test_b2_share_link(self):
        config = {"storage_type": "b2", "b2_application_key_id": "k", "b2_application_key": "s", "b2_bucket_name": "b"}
        with patch("b2sdk.v2.InMemoryAccountInfo"), \
             patch("b2sdk.v2.B2Api") as MockApi:
            mock_api = MagicMock()
            mock_bucket = MagicMock()
            MockApi.return_value = mock_api
            mock_api.get_bucket_by_name.return_value = mock_bucket
            mock_bucket.get_download_url.return_value = "https://b2.example.com/file.zip"
            mock_bucket.get_download_authorization.return_value = "fake-token"
            storage.init_storage(config)
            url, _expires =             storage.generate_share_link("pyxos/test.zip", 3600)
            assert "https://" in url
        storage._state = {}
        storage._b2_bucket = None


class TestDownloadCleanup:
    def test_download_cleanup_on_error(self, tmp_path, mock_cloudinary):
        dest = tmp_path / "dl"
        dest.mkdir()

        with patch("pyxos.storage.cloudinary_url", return_value=("https://fake/x.zip", None)):
            with patch("urllib.request.build_opener") as mbo:
                resp = MagicMock()
                resp.status = 200
                resp.headers = {"Content-Length": "500"}
                resp.read.side_effect = [b"some", b"data", OSError("connection reset")]
                mock_opener = MagicMock()
                mock_opener.open.return_value = resp
                mbo.return_value = mock_opener

                with pytest.raises(RuntimeError, match="Download failed"):
                    storage.download_project("pyxos/test", dest)

                part = dest / "pyxos_test.zip.part"
                assert not part.exists()


class TestPingStorageCloudinary:
    def test_ping_storage_cloudinary(self, mock_cloudinary):
        storage.init_storage({
            "storage_type": "cloudinary",
            "cloudinary_cloud_name": "mycloud",
            "cloudinary_api_key": "key",
            "cloudinary_api_secret": "secret",
        })
        assert storage.ping_storage() is True


class TestStorageEdgeCases:
    def test_init_cloudinary_missing_config(self):
        """Test init_storage raises when Cloudinary config is missing."""
        with pytest.raises(ValueError, match="Missing Cloudinary config"):
            storage.init_storage({"storage_type": "cloudinary"})

    def test_b2_large_upload(self, tmp_path):
        """Test B2 large file upload path (mock)."""
        from unittest.mock import PropertyMock
        
        f = tmp_path / "large.zip"
        f.write_bytes(b"data")
        import os
        fd = os.open(str(f), os.O_RDWR)
        os.ftruncate(fd, 250 * 1024 * 1024)
        os.close(fd)

        b2_cfg = {"storage_type": "b2", "b2_application_key_id": "k", "b2_application_key": "s", "b2_bucket_name": "b"}
        with patch("b2sdk.v2.InMemoryAccountInfo"), \
             patch("b2sdk.v2.B2Api") as MockApi:
            mock_api = MagicMock()
            mock_bucket = MagicMock()
            MockApi.return_value = mock_api
            mock_api.get_bucket_by_name.return_value = mock_bucket
            mock_bucket.get_download_url.return_value = "https://b2.example.com/file.zip"
            mock_bucket.get_download_authorization.return_value = "fake"

            mock_large_file = MagicMock()
            type(mock_large_file).file_id = PropertyMock(return_value="lf123")
            mock_bucket.start_large_file.return_value = mock_large_file
            mock_bucket.upload_part.return_value = MagicMock(content_sha1="fake_sha1")
            mock_bucket.finish_large_file = MagicMock()

            storage.init_storage(b2_cfg)
            url, pid = storage._b2_upload_large(f, "pyxos/large.zip", 250 * 1024 * 1024)
            assert url == "https://b2.example.com/file.zip"
            assert pid == "pyxos/large.zip"
            mock_bucket.start_large_file.assert_called_once()
            mock_bucket.finish_large_file.assert_called_once()
        
        storage._state = {}
        storage._b2_bucket = None

    def test_resume_status_200_reset(self, tmp_path, mock_cloudinary):
        """Test resume download when server returns 200 (full restart)."""
        storage._state = {}
        storage.init_storage({
            "storage_type": "cloudinary",
            "cloudinary_cloud_name": "mycloud",
            "cloudinary_api_key": "key",
            "cloudinary_api_secret": "secret",
        })
        dest = tmp_path / "dl"
        dest.mkdir()
        part = dest / "pyxos_test.zip.part"
        part.write_bytes(b"old_partial")

        with patch("pyxos.storage.cloudinary_url", return_value=("https://fake/x.zip", None)):
            with patch("urllib.request.build_opener") as mbo:
                resp = MagicMock()
                resp.status = 200
                resp.headers = {"Content-Length": "12"}
                resp.read.side_effect = [b"new_content", b""]
                mock_opener = MagicMock()
                mock_opener.open.return_value = resp
                mbo.return_value = mock_opener

                result = storage.download_project("pyxos/test", dest)
                assert result.exists()

    def test_fmt_helper(self):
        """Test _fmt size formatter."""
        assert "12.0 MB" in storage._fmt(12 * 1024 * 1024)
        assert storage._fmt(500) != storage._fmt(500 * 1024 * 1024)
