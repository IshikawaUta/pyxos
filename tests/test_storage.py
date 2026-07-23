from unittest.mock import patch, MagicMock

import pytest
import cloudinary

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
        url, pid = storage.upload_project(archive, "myproject")
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
            with patch("urllib.request.urlopen") as mu:
                resp = MagicMock()
                resp.headers = {"Content-Length": "20"}
                resp.read.side_effect = [b"fake zip content", b""]
                mu.return_value = resp

                result = storage.download_project("pyxos/t", dest)

        assert result.exists()
        assert result.name == "pyxos_t.zip"
        assert result.read_bytes() == b"fake zip content"

    def test_download_no_content_length(self, tmp_path, mock_cloudinary):
        dest = tmp_path / "dl"
        dest.mkdir()

        with patch("pyxos.storage.cloudinary_url", return_value=("https://fake/x.zip", None)):
            with patch("urllib.request.urlopen") as mu:
                resp = MagicMock()
                resp.headers = {}
                resp.read.side_effect = [b"data", b""]
                mu.return_value = resp

                result = storage.download_project("pyxos/t", dest)

        assert result.exists()

    def test_download_error(self, tmp_path, mock_cloudinary):
        dest = tmp_path / "dl"
        dest.mkdir()

        with patch("pyxos.storage.cloudinary_url", return_value=("https://fake/x.zip", None)):
            resp = MagicMock()
            resp.headers = {"Content-Length": "500"}
            resp.read.side_effect = IOError("Network down")
            with patch("urllib.request.urlopen", return_value=resp):
                with pytest.raises(RuntimeError, match="Download failed"):
                    storage.download_project("pyxos/t", dest)
            archive_path = dest / "pyxos_t.zip"
            assert not archive_path.exists()


class TestPingCloudinary:
    def test_ping_success(self, mock_cloudinary):
        assert storage.ping_cloudinary() is True

    def test_ping_failure(self):
        with patch("cloudinary.api.ping", side_effect=cloudinary.exceptions.Error("down")):
            assert storage.ping_cloudinary() is False


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

    def test_b2_download(self, tmp_path):
        dest = tmp_path / "dl"
        dest.mkdir()
        mock_dl = MagicMock()
        self.bucket.download_file_by_name.return_value = mock_dl

        def fake_save_to(path):
            with open(path, "wb") as f:
                f.write(b"b2_content")

        mock_dl.save_to.side_effect = fake_save_to

        result = storage.download_project("pyxos/myproject.zip", dest)
        assert result.exists()
        assert result.read_bytes() == b"b2_content"

    def test_b2_ping(self):
        assert storage.ping_storage() is True

    def test_b2_ping_failure(self):
        from b2sdk.v2.exception import B2Error
        self.bucket.ls.side_effect = B2Error("auth")
        assert storage.ping_storage() is False
