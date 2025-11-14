import hashlib
from typing import Optional

from fastapi import Request

from onyx.configs.constants import SESSION_KEY


def compute_sha256_hash(text: str) -> str:
    """Вычисляет SHA-256 хеш строки."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def extract_hashed_cookie(request: Request) -> Optional[str]:
    """Извлекает сессионную куки и возвращает её хешированную версию."""
    raw_cookie = request.cookies.get(SESSION_KEY)
    if not raw_cookie:
        return None
    return compute_sha256_hash(raw_cookie)
