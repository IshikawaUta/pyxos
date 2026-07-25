import base64
import hashlib
import os
import struct
import tempfile
from pathlib import Path

try:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    _BACKEND = "cryptography"
except ImportError:
    try:
        from Crypto.Cipher import AES as PycryptoAES
        from Crypto.Random import get_random_bytes as pycrypto_random
        from Crypto.Util.Padding import pad, unpad
        _BACKEND = "pycryptodome"
    except ImportError:
        _BACKEND = "fallback"

SALT_SIZE = 16
IV_SIZE = 16
KEY_SIZE = 32
ITERATIONS = 100000
CHUNK_SIZE = 1024 * 1024


def _derive_key(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS, dklen=KEY_SIZE)



def _encrypt_cryptography_stream(src_file, key, iv, salt):
    padder = padding.PKCS7(128).padder()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    while True:
        chunk = src_file.read(CHUNK_SIZE)
        if not chunk:
            break
        padded = padder.update(chunk)
        if padded:
            yield encryptor.update(padded)
    padded = padder.finalize()
    if padded:
        yield encryptor.update(padded)
    yield encryptor.finalize()



def _encrypt_pycryptodome(data, password):
    salt = pycrypto_random(SALT_SIZE)
    key = _derive_key(password, salt)
    iv = pycrypto_random(IV_SIZE)
    cipher = PycryptoAES.new(key, PycryptoAES.MODE_CBC, iv)
    encrypted = cipher.encrypt(pad(data, PycryptoAES.block_size))
    return salt + iv + encrypted


def _decrypt_pycryptodome(data, password):
    salt = data[:SALT_SIZE]
    iv = data[SALT_SIZE:SALT_SIZE + IV_SIZE]
    encrypted = data[SALT_SIZE + IV_SIZE:]
    key = _derive_key(password, salt)
    cipher = PycryptoAES.new(key, PycryptoAES.MODE_CBC, iv)
    return unpad(cipher.decrypt(encrypted), PycryptoAES.block_size)


def _encrypt_fallback(data, password):
    salt = os.urandom(SALT_SIZE)
    key = _derive_key(password, salt)
    iv = os.urandom(IV_SIZE)
    encrypted = bytearray()
    prev_block = iv
    block_size = 16
    for i in range(0, len(data), block_size):
        block = data[i:i + block_size]
        if len(block) < block_size:
            pad_len = block_size - len(block)
            block = block + bytes([pad_len] * pad_len)
        xor_block = bytes(a ^ b for a, b in zip(block, prev_block[:len(block)]))
        keystream = _generate_keystream(key, iv, salt, len(block), i)
        enc_block = bytes(a ^ b for a, b in zip(xor_block, keystream))
        encrypted.extend(enc_block)
        prev_block = enc_block
    return salt + iv + bytes(encrypted)


def _decrypt_fallback(data, password):
    salt = data[:SALT_SIZE]
    iv = data[SALT_SIZE:SALT_SIZE + IV_SIZE]
    encrypted = data[SALT_SIZE + IV_SIZE:]
    key = _derive_key(password, salt)
    decrypted = bytearray()
    prev_block = iv
    block_size = 16
    for i in range(0, len(encrypted), block_size):
        block = encrypted[i:i + block_size]
        keystream = _generate_keystream(key, iv, salt, len(block), i)
        xor_block = bytes(a ^ b for a, b in zip(block, keystream))
        dec_block = bytes(a ^ b for a, b in zip(xor_block, prev_block[:len(block)]))
        if i + block_size >= len(encrypted):
            pad_len = dec_block[-1]
            if 1 <= pad_len <= block_size:
                padding_bytes = dec_block[-pad_len:]
                if all(b == pad_len for b in padding_bytes):
                    dec_block = dec_block[:-pad_len]
                else:
                    raise ValueError("Invalid PKCS7 padding")
            else:
                raise ValueError("Invalid PKCS7 padding")
        decrypted.extend(dec_block)
        prev_block = block
    return bytes(decrypted)


def _generate_keystream(key, iv, salt, length, offset):
    result = b""
    counter = 0
    while len(result) < length:
        h = hashlib.sha256()
        h.update(key)
        h.update(iv)
        h.update(salt)
        h.update(struct.pack(">I", counter))
        h.update(struct.pack(">I", offset))
        result += h.digest()
        counter += 1
    return result[:length]


def encrypt_archive(archive_path, password):
    archive_path = Path(archive_path)

    salt = os.urandom(SALT_SIZE)
    iv = os.urandom(IV_SIZE)
    key = _derive_key(password, salt)

    enc_path = archive_path.with_suffix(archive_path.suffix + ".enc")

    if _BACKEND == "cryptography":
        with open(archive_path, "rb") as src, \
             open(enc_path, "wb") as dst:
            dst.write(b"PYXOS_AES\x01")
            dst.write(base64.b64encode(salt + iv))
            temp_fd, temp_path = tempfile.mkstemp()
            try:
                with open(temp_fd, "wb") as tmp:
                    tmp.writelines(_encrypt_cryptography_stream(src, key, iv, salt))
                with open(temp_path, "rb") as tmp:
                    while True:
                        b64_chunk = tmp.read(48)
                        if not b64_chunk:
                            break
                        dst.write(base64.b64encode(b64_chunk))
            finally:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
    else:
        with open(archive_path, "rb") as f:
            data = f.read()

        if _BACKEND == "pycryptodome":
            encrypted_data = _encrypt_pycryptodome(data, password)
        else:
            encrypted_data = _encrypt_fallback(data, password)

        encoded = base64.b64encode(encrypted_data)
        with open(enc_path, "wb") as f:
            f.write(b"PYXOS_AES\x01" + encoded)

    return enc_path


def decrypt_archive(encrypted_path, password):
    encrypted_path = Path(encrypted_path)

    with open(encrypted_path, "rb") as f:
        magic_len = len(b"PYXOS_AES\x01")
        header = f.read(magic_len)
        if header != b"PYXOS_AES\x01":
            raise ValueError("Invalid encrypted file format")

        if _BACKEND == "cryptography":
            b64_header = b""
            while len(b64_header) < 44:
                b = f.read(1)
                if not b:
                    break
                b64_header += b
            combined = base64.b64decode(b64_header)
        else:
            combined = b""

    dec_path = encrypted_path.with_suffix("")
    if dec_path.suffix == ".enc":
        dec_path = dec_path.with_suffix("")
    if not dec_path.suffix:
        dec_path = dec_path.with_suffix(".zip")

    if _BACKEND == "cryptography":
        salt = combined[:SALT_SIZE]
        iv = combined[SALT_SIZE:SALT_SIZE + IV_SIZE]

        with open(encrypted_path, "rb") as src, \
             open(dec_path, "wb") as dst:
            src.seek(magic_len + len(b64_header))

            decoder = _base64_decode(src)
            key = _derive_key(password, salt)
            cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
            decryptor = cipher.decryptor()
            unpadder = padding.PKCS7(128).unpadder()

            buffer = b""
            for b64_chunk in decoder:
                buffer += decryptor.update(b64_chunk)
                while len(buffer) >= CHUNK_SIZE + 32:
                    data = buffer[:CHUNK_SIZE + 32]
                    buffer = buffer[CHUNK_SIZE + 32:]
                    unpadded = unpadder.update(data)
                    if unpadded:
                        dst.write(unpadded)

            buffer += decryptor.finalize()
            while buffer:
                unpadded = unpadder.update(buffer[:CHUNK_SIZE])
                buffer = buffer[CHUNK_SIZE:]
                if unpadded:
                    dst.write(unpadded)
            final = unpadder.finalize()
            if final:
                dst.write(final)
    else:
        with open(encrypted_path, "rb") as f:
            full = f.read()
        magic = b"PYXOS_AES\x01"
        encoded = full[len(magic):]
        encrypted_data = base64.b64decode(encoded)

        if _BACKEND == "pycryptodome":
            decrypted_data = _decrypt_pycryptodome(encrypted_data, password)
        else:
            decrypted_data = _decrypt_fallback(encrypted_data, password)

        with open(dec_path, "wb") as f:
            f.write(decrypted_data)

    return dec_path


def _base64_decode(src_file):
    buffer = b""
    while True:
        chunk = src_file.read(4)
        if not chunk:
            break
        buffer += chunk
        padding = buffer.count(b"=")
        if padding > 0 or len(buffer) >= 4 or len(buffer) >= 48:
            dec_chunk = base64.b64decode(buffer)
            buffer = b""
            yield dec_chunk
    if buffer:
        yield base64.b64decode(buffer)
