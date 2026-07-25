import base64
import logging
import httpx
from typing import Optional
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger(__name__)

# HKDF info strings per WhatsApp media type
WA_MEDIA_HKDF_INFO = {
    "image": b"WhatsApp Image Keys",
    "video": b"WhatsApp Video Keys",
    "audio": b"WhatsApp Audio Keys",
    "document": b"WhatsApp Document Keys",
    "sticker": b"WhatsApp Image Keys",
}


def decrypt_whatsapp_media(encrypted_data: bytes, media_key_b64: str, media_type: str = "document") -> bytes:
    """
    Decrypt media downloaded from WhatsApp CDN.
    Uses HKDF-SHA256 key derivation + AES-256-CBC decryption.
    """
    media_key = base64.b64decode(media_key_b64)
    hkdf_info = WA_MEDIA_HKDF_INFO.get(media_type.lower(), b"WhatsApp Document Keys")

    # HKDF expand: derive 112 bytes
    derivative = HKDF(
        algorithm=hashes.SHA256(),
        length=112,
        salt=None,
        info=hkdf_info,
        backend=default_backend()
    ).derive(media_key)

    iv = derivative[:16]
    cipher_key = derivative[16:48]

    # Encrypted file = [encrypted_data_body] + [10 bytes MAC]
    file_enc = encrypted_data[:-10]

    # AES-256-CBC decrypt
    cipher = Cipher(algorithms.AES(cipher_key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted = decryptor.update(file_enc) + decryptor.finalize()

    # Remove PKCS7 padding
    if len(decrypted) > 0:
        pad_len = decrypted[-1]
        if 0 < pad_len <= 16:
            decrypted = decrypted[:-pad_len]

    return decrypted


async def download_and_decrypt_wa_media(
    media_key: str,
    direct_path: Optional[str] = None,
    url: Optional[str] = None,
    media_type: str = "document"
) -> bytes:
    """
    Downloads encrypted media directly from WhatsApp CDN and decrypts it.
    """
    download_url = url
    if not download_url and direct_path:
        download_url = f"https://mmg.whatsapp.net{direct_path}"

    if not download_url:
        raise ValueError("Tidak ada URL atau directPath untuk mengunduh media.")

    logger.info(f"Downloading encrypted WhatsApp media from CDN: {download_url[:80]}...")

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br",
        "Origin": "https://web.whatsapp.com",
        "Referer": "https://web.whatsapp.com/"
    }

    transport = httpx.AsyncHTTPTransport(retries=2)
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, transport=transport) as client:
        response = await client.get(download_url, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"Gagal download media dari CDN WhatsApp (HTTP {response.status_code})")
        encrypted_data = response.content

    logger.info(f"Downloaded {len(encrypted_data)} bytes. Decrypting...")
    decrypted_data = decrypt_whatsapp_media(encrypted_data, media_key, media_type=media_type)
    logger.info(f"Successfully decrypted to {len(decrypted_data)} bytes.")

    return decrypted_data
