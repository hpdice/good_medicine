import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings


class FieldEncryptor:
    """AES-256-GCM 필드 레벨 암호화 - 건강정보 등 민감 데이터 보호"""

    def __init__(self) -> None:
        key_bytes = bytes.fromhex(settings.FIELD_ENCRYPTION_KEY)
        if len(key_bytes) != 32:
            raise ValueError("FIELD_ENCRYPTION_KEY must be 32 bytes (64 hex chars)")
        self._aesgcm = AESGCM(key_bytes)

    def encrypt(self, data: dict | list | str) -> str:
        nonce = os.urandom(12)
        plaintext = json.dumps(data, ensure_ascii=False).encode()
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, None)
        combined = nonce + ciphertext
        return base64.b64encode(combined).decode()

    def decrypt(self, encrypted: str) -> dict | list | str:
        combined = base64.b64decode(encrypted.encode())
        nonce, ciphertext = combined[:12], combined[12:]
        plaintext = self._aesgcm.decrypt(nonce, ciphertext, None)
        return json.loads(plaintext.decode())


_encryptor: FieldEncryptor | None = None


def get_encryptor() -> FieldEncryptor:
    global _encryptor
    if _encryptor is None:
        _encryptor = FieldEncryptor()
    return _encryptor
