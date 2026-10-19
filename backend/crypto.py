import base64
import hashlib
from cryptography.fernet import Fernet
from config import CREDENTIAL_ENCRYPTION_KEY, JWT_SECRET_KEY


def _get_fernet_key() -> bytes:
    """
    Get or derive a 32-byte URL-safe base64-encoded key for Fernet.
    If CREDENTIAL_ENCRYPTION_KEY is provided in config/env, validate and use it.
    Otherwise, derive a deterministic key from JWT_SECRET_KEY using SHA-256.
    """
    if CREDENTIAL_ENCRYPTION_KEY and len(CREDENTIAL_ENCRYPTION_KEY.strip()) > 0:
        raw = CREDENTIAL_ENCRYPTION_KEY.strip().encode()
        try:
            # Validate if it's already a valid Fernet key
            Fernet(raw)
            return raw
        except Exception:
            # If user provided a passphrase instead of base64 key, derive a valid Fernet key
            digest = hashlib.sha256(raw).digest()
            return base64.urlsafe_b64encode(digest)

    # Deterministic fallback derived from JWT_SECRET_KEY
    digest = hashlib.sha256(JWT_SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def get_fernet_cipher() -> Fernet:
    """Return a Fernet cipher instance initialized with the master key."""
    return Fernet(_get_fernet_key())


def encrypt_secret(plaintext: str) -> str:
    """
    Encrypt a plaintext secret (such as AWS Access Key or Secret Key)
    using Fernet AES-256 symmetric encryption.
    Returns the ciphertext string.
    """
    if not plaintext:
        return ""
    cipher = get_fernet_cipher()
    token = cipher.encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    """
    Decrypt a ciphertext string back into plaintext using Fernet.
    """
    if not ciphertext:
        return ""
    cipher = get_fernet_cipher()
    decrypted = cipher.decrypt(ciphertext.encode("utf-8"))
    return decrypted.decode("utf-8")


def mask_access_key(key: str) -> str:
    """
    Mask an access key for safe UI display (e.g. AKIA••••••••7B2D).
    Never exposes full key content.
    """
    if not key:
        return ""
    s = key.strip()
    if len(s) <= 8:
        return "••••••••"
    return f"{s[:4]}••••••••{s[-4:]}"
