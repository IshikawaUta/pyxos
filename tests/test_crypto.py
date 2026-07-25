import os
import io
import base64
import pytest
from pyxos import crypto

class TestCrypto:
    def test_encrypt_decrypt_roundtrip(self, tmp_path):
        """Encrypt then decrypt should return original content."""
        original = tmp_path / "test.zip"
        original.write_bytes(b"hello world zip content 12345")
        
        encrypted = crypto.encrypt_archive(original, "mypassword")
        assert encrypted.exists()
        assert encrypted.suffix == ".enc"
        assert encrypted.read_bytes() != b"hello world zip content 12345"
        
        decrypted = crypto.decrypt_archive(encrypted, "mypassword")
        assert decrypted.exists()
        assert decrypted.read_bytes() == b"hello world zip content 12345"

    def test_decrypt_wrong_password(self, tmp_path):
        original = tmp_path / "test.zip"
        original.write_bytes(b"data")
        encrypted = crypto.encrypt_archive(original, "correct")
        
        with pytest.raises((ValueError, RuntimeError, Exception)):
            crypto.decrypt_archive(encrypted, "wrong")

    def test_encrypt_empty_file(self, tmp_path):
        original = tmp_path / "empty.zip"
        original.write_bytes(b"")
        
        encrypted = crypto.encrypt_archive(original, "pass")
        assert encrypted.exists()
        decrypted = crypto.decrypt_archive(encrypted, "pass")
        assert decrypted.read_bytes() == b""

    def test_encrypt_large_file(self, tmp_path):
        original = tmp_path / "large.zip"
        data = os.urandom(100 * 1024)  # 100KB
        original.write_bytes(data)
        
        encrypted = crypto.encrypt_archive(original, "pass")
        decrypted = crypto.decrypt_archive(encrypted, "pass")
        assert decrypted.read_bytes() == data

    def test_encrypt_creates_new_file(self, tmp_path):
        original = tmp_path / "test.zip"
        original.write_bytes(b"content")
        
        crypto.encrypt_archive(original, "pass")
        # Original should still exist
        assert original.exists()
        assert original.read_bytes() == b"content"

    def test_encrypt_with_special_chars_password(self, tmp_path):
        original = tmp_path / "test.zip"
        original.write_bytes(b"data")
        encrypted = crypto.encrypt_archive(original, "p@$$w0rd!日本語")
        decrypted = crypto.decrypt_archive(encrypted, "p@$$w0rd!日本語")
        assert decrypted.read_bytes() == b"data"

    def test_decrypt_corrupted_file(self, tmp_path):
        original = tmp_path / "test.zip"
        original.write_bytes(b"valid data")
        encrypted = crypto.encrypt_archive(original, "pass")
        # Corrupt the encrypted file
        encrypted.write_bytes(b"corrupted" + encrypted.read_bytes()[10:])
        with pytest.raises((ValueError, RuntimeError, Exception)):
            crypto.decrypt_archive(encrypted, "pass")

    def test_decrypt_empty_file(self, tmp_path):
        f = tmp_path / "empty.enc"
        f.write_bytes(b"")
        with pytest.raises((ValueError, RuntimeError, Exception)):
            crypto.decrypt_archive(f, "pass")

    def test_decrypt_no_zip_suffix(self, tmp_path):
        """Decrypt file where dec_path has no .zip suffix."""
        original = tmp_path / "test.zip"
        original.write_bytes(b"content with suffix")
        encrypted = crypto.encrypt_archive(original, "pass")
        # Rename so decrypted path won't naturally have .zip suffix
        renamed = tmp_path / "test.enc"
        encrypted.rename(renamed)
        
        decrypted = crypto.decrypt_archive(renamed, "pass")
        assert decrypted.exists()
        assert decrypted.read_bytes() == b"content with suffix"

    def test_base64_decode_streaming(self, tmp_path):
        """Test _base64_decode handles chunked base64 data."""
        from pyxos.crypto import _base64_decode
        
        data = b"PYXOS_AES\x01" + base64.b64encode(os.urandom(48) + b"Hello World!" * 10)
        src = io.BytesIO(data)
        src.read(len(b"PYXOS_AES\x01"))
        
        result = b""
        for chunk in _base64_decode(src):
            result += chunk
        assert len(result) > 10

    def test_base64_decode_small(self, tmp_path):
        """Test _base64_decode with small data."""
        from pyxos.crypto import _base64_decode
        
        data = base64.b64encode(b"hello")
        src = io.BytesIO(data)
        
        result = b""
        for chunk in _base64_decode(src):
            result += chunk
        assert result == b"hello"

    def test_base64_decode_padded(self, tmp_path):
        """Test _base64_decode with = padding."""
        from pyxos.crypto import _base64_decode
        
        data = base64.b64encode(b"ab")
        src = io.BytesIO(data)
        
        result = b""
        for chunk in _base64_decode(src):
            result += chunk
        assert result == b"ab"
        """Decrypt file with double .enc suffix."""
        original = tmp_path / "file.zip"
        original.write_bytes(b"double enc test data here")
        encrypted = crypto.encrypt_archive(original, "pass")
        # Rename to double .enc
        renamed = tmp_path / "file.zip.enc.enc"
        encrypted.rename(renamed)
        
        decrypted = crypto.decrypt_archive(renamed, "pass")
        assert decrypted.exists()
        assert decrypted.read_bytes() == b"double enc test data here"


class TestCryptoFallback:
    def test_fallback_backend_roundtrip(self, tmp_path, monkeypatch):
        """Force the fallback (hashlib) backend and test encryption."""
        import pyxos.crypto as crypto
        monkeypatch.setattr(crypto, "_BACKEND", "fallback")

        original = tmp_path / "test.zip"
        original.write_bytes(b"testing fallback encryption backend")

        encrypted = crypto.encrypt_archive(original, "passwd")
        assert encrypted.exists()

        decrypted = crypto.decrypt_archive(encrypted, "passwd")
        assert decrypted.read_bytes() == b"testing fallback encryption backend"

    def test_pycryptodome_backend_roundtrip(self, tmp_path, monkeypatch):
        """Test pycryptodome backend if available."""
        try:
            from Crypto.Cipher import AES as PycryptoAES
            from Crypto.Util.Padding import pad, unpad
            from Crypto.Random import get_random_bytes as pycrypto_random
        except ImportError:
            pytest.skip("pycryptodome not installed")

        import pyxos.crypto as crypto
        monkeypatch.setattr(crypto, "_BACKEND", "pycryptodome")
        # Inject pycryptodome functions that weren't imported at module level
        crypto.PycryptoAES = PycryptoAES
        crypto.pad = pad
        crypto.unpad = unpad
        crypto.pycrypto_random = pycrypto_random

        original = tmp_path / "test.zip"
        original.write_bytes(b"testing pycryptodome backend")

        encrypted = crypto.encrypt_archive(original, "passwd")
        decrypted = crypto.decrypt_archive(encrypted, "passwd")
        assert decrypted.read_bytes() == b"testing pycryptodome backend"
