"""Cifratura e accesso alle chiavi personali associate all'identità SSO."""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken


@dataclass(frozen=True)
class UserKeys:
    etoro_api_key: str = ""
    etoro_user_key: str = ""
    openai_api_key: str = ""

    @property
    def etoro_configured(self) -> bool:
        return bool(self.etoro_api_key and self.etoro_user_key)


def _cipher() -> Fernet:
    secret = os.environ.get("TRADING_CREDENTIALS_SECRET", "")
    if not secret:
        raise RuntimeError("TRADING_CREDENTIALS_SECRET non configurato")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def _encrypt(value: str) -> str:
    return _cipher().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt(value: str | None) -> str:
    if not value:
        return ""
    try:
        return _cipher().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("credenziale cifrata non decifrabile") from exc


def get_user_keys(repo, user_id: str) -> UserKeys:
    """Chiavi personali dell'identità SSO. Nessun fallback da environment:
    eToro e OpenAI si configurano solo da Impostazioni → Chiavi API personali."""
    row = repo.get_user_credentials(user_id)
    if row is None:
        return UserKeys()
    return UserKeys(
        etoro_api_key=_decrypt(row.etoro_api_key_encrypted),
        etoro_user_key=_decrypt(row.etoro_user_key_encrypted),
        openai_api_key=_decrypt(row.openai_api_key_encrypted),
    )


def update_user_keys(
    repo,
    user_id: str,
    *,
    email: str | None,
    display_name: str | None,
    etoro_api_key: str | None,
    etoro_user_key: str | None,
    openai_api_key: str | None,
) -> UserKeys:
    current = get_user_keys(repo, user_id)
    updated = UserKeys(
        etoro_api_key=current.etoro_api_key if etoro_api_key is None else etoro_api_key.strip(),
        etoro_user_key=current.etoro_user_key if etoro_user_key is None else etoro_user_key.strip(),
        openai_api_key=current.openai_api_key if openai_api_key is None else openai_api_key.strip(),
    )
    repo.set_user_credentials(
        user_id,
        email=email,
        display_name=display_name,
        etoro_api_key_encrypted=_encrypt(updated.etoro_api_key) if updated.etoro_api_key else None,
        etoro_user_key_encrypted=_encrypt(updated.etoro_user_key) if updated.etoro_user_key else None,
        openai_api_key_encrypted=_encrypt(updated.openai_api_key) if updated.openai_api_key else None,
    )
    return updated
