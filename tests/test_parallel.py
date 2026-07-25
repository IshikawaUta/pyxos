from unittest.mock import MagicMock, patch
import pytest
from pyxos import parallel


class TestParallelDownload:
    def test_download_single_chunk(self, tmp_path):
        data = b"x" * 1000
        dest = tmp_path / "output.bin"

        with patch("urllib.request.urlopen") as mu:
            resp = MagicMock()
            resp.headers = {"Content-Length": "1000", "Accept-Ranges": "bytes"}
            resp.__enter__.return_value = resp
            resp.read.return_value = data
            mu.return_value = resp

            result = parallel.parallel_download("https://example.com/file", dest, num_workers=2)

        assert result.exists()
        assert result.read_bytes() == data

    def test_download_no_range_support(self, tmp_path):
        data = b"small"
        dest = tmp_path / "output.bin"

        with patch("urllib.request.urlopen") as mu:
            resp = MagicMock()
            resp.headers = {"Content-Length": "5"}
            resp.__enter__.return_value = resp
            resp.read.return_value = data
            mu.return_value = resp

            result = parallel.parallel_download("https://example.com/file", dest)

        assert result.exists()
        assert result.read_bytes() == data

    def test_download_large_file(self, tmp_path):
        data = b"a" * 3_000_000
        dest = tmp_path / "large.bin"
        chunk1 = data[:1_500_000]
        chunk2 = data[1_500_000:]

        with patch("urllib.request.urlopen") as mu, \
             patch("urllib.request.Request"):
            resp_head = MagicMock()
            resp_head.__enter__.return_value = resp_head
            resp_head.headers = {"Content-Length": "3000000", "Accept-Ranges": "bytes"}

            resp1 = MagicMock()
            resp1.__enter__.return_value = resp1
            resp1.read.return_value = chunk1
            resp2 = MagicMock()
            resp2.__enter__.return_value = resp2
            resp2.read.return_value = chunk2

            mu.side_effect = [resp_head, resp1, resp2]

            result = parallel.parallel_download("https://example.com/file", dest, num_workers=2)

        assert result.exists()
        assert result.read_bytes() == data

    def test_download_network_error(self, tmp_path):
        dest = tmp_path / "output.bin"
        with patch("urllib.request.urlopen") as mu:
            mu.side_effect = Exception("Network error")
            with pytest.raises(Exception):
                parallel.parallel_download("https://example.com/file", dest)

    def test_download_empty_file(self, tmp_path):
        dest = tmp_path / "empty.bin"
        with patch("urllib.request.urlopen") as mu:
            resp = MagicMock()
            resp.headers = {"Content-Length": "0", "Accept-Ranges": "bytes"}
            resp.__enter__.return_value = resp
            resp.read.return_value = b""
            mu.return_value = resp
            result = parallel.parallel_download("https://example.com/file", dest)
        assert result.exists()


class TestParallelUpload:
    def test_parallel_upload_small_b2_file(self, tmp_path):
        f = tmp_path / "small.zip"
        f.write_bytes(b"smalldata")

        with patch("pyxos.storage.upload_project") as mock_upload:
            mock_upload.return_value = ("https://fake.url/small.zip", "pyxos/test")
            url, pid = parallel.parallel_upload(str(f), "test", "b2")

        assert mock_upload.called
        assert pid is not None
        assert url is not None

    def test_parallel_upload_cloudinary(self, tmp_path):
        f = tmp_path / "test.zip"
        f.write_bytes(b"data")

        with patch("pyxos.storage.upload_project") as mock_upload:
            mock_upload.return_value = ("https://cloudinary.com/fake.zip", "pyxos/test")
            url, pid = parallel.parallel_upload(str(f), "test", "cloudinary")

        assert mock_upload.called
        assert url is not None
        assert pid is not None

    def test_upload_unknown_storage_type(self, tmp_path):
        """Parallel upload with unknown storage type."""
        f = tmp_path / "test.zip"
        f.write_bytes(b"data")
        with patch("pyxos.storage.upload_project") as mock_upload:
            mock_upload.return_value = (None, None)
            url, pid = parallel.parallel_upload(str(f), "test", "s3")
            assert url is None
            assert pid is None

    def test_split_file(self, tmp_path):
        """Test _split_file creates correct parts."""
        f = tmp_path / "big.zip"
        f.write_bytes(b"A" * 10000 + b"B" * 10000)
        parts = parallel._split_file(str(f), tmp_path, 10000, "testproj")
        assert len(parts) == 2
        assert parts[0].read_bytes() == b"A" * 10000
        assert parts[1].read_bytes() == b"B" * 10000

    def test_download_chunk_error(self, tmp_path):
        """Test parallel download falls back to sequential on chunk error."""
        dest = tmp_path / "out.bin"
        with patch("urllib.request.urlopen") as mu, \
             patch("urllib.request.Request"):
            resp_head = MagicMock()
            resp_head.headers = {"Content-Length": "20000", "Accept-Ranges": "bytes"}
            
            resp1 = MagicMock()
            resp1.__enter__.return_value = resp1
            resp1.read.return_value = b"A" * 10000
            resp2 = MagicMock()
            resp2.__enter__.return_value = resp2
            resp2.read.side_effect = Exception("chunk error")
            resp_fallback = MagicMock()
            resp_fallback.__enter__.return_value = resp_fallback
            resp_fallback.read.return_value = b"fallback_data"
            
            mu.side_effect = [resp_head, resp1, resp2, resp_fallback]
            
            result = parallel.parallel_download("https://example.com/file", dest, num_workers=2)
            assert result.exists()

    def test_download_url_open_error(self, tmp_path):
        """Test when HEAD request fails."""
        dest = tmp_path / "output.bin"
        from urllib.error import URLError
        with patch("urllib.request.urlopen") as mu:
            mu.side_effect = URLError("DNS error")
            with pytest.raises(Exception):
                parallel.parallel_download("https://bad.example.com/file", dest)

    def test_b2_parallel_upload_large(self, tmp_path):
        """Test B2 parallel upload with file > 50MB chunk size."""
        import os
        
        f = tmp_path / "big.zip"
        f.write_bytes(b"start")
        fd = os.open(str(f), os.O_RDWR)
        os.ftruncate(fd, 51 * 1024 * 1024)
        os.close(fd)
        
        with patch("pyxos.storage._b2_bucket") as mock_bucket, \
             patch("b2sdk.v2.UploadSourceLocalFile") as mock_source, \
             patch("pyxos.storage._state", {}), \
             patch("pyxos.storage.init_storage"):
            mock_bucket.upload = MagicMock()
            mock_bucket.get_download_url.return_value = "https://b2.example.com/part0001"
            mock_source.return_value = MagicMock()
            
            url, pid = parallel.parallel_upload(str(f), "testproj", "b2")
            
            assert url == "https://b2.example.com/part0001"
            assert pid == "pyxos/testproj.zip"
            assert mock_bucket.upload.call_count >= 1
