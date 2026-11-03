"""Experimental GS public-key and Blowfish wire formats.

Derived from the XIII USA PS2 executable's network overlay. These helpers have
not yet been validated against a running retail client.
"""
from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.decrepit.ciphers.algorithms import Blowfish
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, modes

RSA_FIELD_BYTES = 128
RSA_PUBLIC_SIZE = 4 + 2 * RSA_FIELD_BYTES
MAX_PLAINTEXT = 0xFFFF


@dataclass(frozen=True)
class GSPublicKey:
    """GS public key: native little-endian bit count, big-endian integers."""

    bits: int
    modulus: int
    exponent: int

    @classmethod
    def decode(cls, data: bytes) -> "GSPublicKey":
        if len(data) != RSA_PUBLIC_SIZE:
            raise ValueError(f"GS public key must be {RSA_PUBLIC_SIZE} bytes")
        bits = int.from_bytes(data[:4], "little")
        modulus = int.from_bytes(data[4:132], "big")
        exponent = int.from_bytes(data[132:260], "big")
        key = cls(bits, modulus, exponent)
        key._validate()
        return key

    def _validate(self) -> None:
        if not 508 <= self.bits <= 1024:
            raise ValueError("unsupported GS RSA key size")
        if self.modulus <= 0 or self.modulus.bit_length() > self.bits:
            raise ValueError("RSA modulus does not fit the declared size")
        if self.exponent < 3 or self.exponent % 2 == 0 or self.exponent >= self.modulus:
            raise ValueError("invalid RSA public exponent")

    def encode(self) -> bytes:
        self._validate()
        return (self.bits.to_bytes(4, "little")
                + self.modulus.to_bytes(RSA_FIELD_BYTES, "big")
                + self.exponent.to_bytes(RSA_FIELD_BYTES, "big"))

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt key material with RSA PKCS #1 v1.5 type-2 padding."""
        self._validate()
        public_key = rsa.RSAPublicNumbers(self.exponent, self.modulus).public_key()
        return public_key.encrypt(plaintext, padding.PKCS1v15())


def _reverse_words(data: bytes) -> bytes:
    """Convert the client's little-endian 32-bit words to/from library order."""
    return b"".join(data[i:i + 4][::-1] for i in range(0, len(data), 4))


def _crypt_blocks(key: bytes, data: bytes, *, decrypt: bool) -> bytes:
    if not 4 <= len(key) <= 56:
        raise ValueError("Blowfish key must contain 4 to 56 bytes")
    if len(data) % 8:
        raise ValueError("Blowfish data must be a multiple of eight bytes")
    cipher = Cipher(Blowfish(key), modes.ECB())
    worker = cipher.decryptor() if decrypt else cipher.encryptor()
    result = worker.update(_reverse_words(data)) + worker.finalize()
    return _reverse_words(result)


def encrypt_payload(key: bytes, plaintext: bytes) -> bytes:
    """Zero-pad to eight bytes, encrypt blocks, append original u16 length."""
    if len(plaintext) > MAX_PLAINTEXT:
        raise ValueError("GS encrypted payload exceeds 65535 bytes")
    pad = (-len(plaintext)) % 8
    encrypted = _crypt_blocks(key, plaintext + bytes(pad), decrypt=False)
    return encrypted + len(plaintext).to_bytes(2, "little")


def decrypt_payload(key: bytes, payload: bytes) -> bytes:
    """Decrypt a bounded GS encrypted payload and remove its zero padding."""
    if len(payload) < 2 or (len(payload) - 2) % 8:
        raise ValueError("invalid GS encrypted payload length")
    size = int.from_bytes(payload[-2:], "little")
    expected = (size + 7) // 8 * 8
    if len(payload) - 2 != expected:
        raise ValueError("GS length trailer does not match encrypted blocks")
    return _crypt_blocks(key, payload[:-2], decrypt=True)[:size]
