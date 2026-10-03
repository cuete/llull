"""Tests for MSA (personal Microsoft account) token validation.

These call get_current_user / _validate_aad_token directly rather than through the
`client` fixture, since that fixture overrides get_current_user wholesale for all
other tests.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.config import Settings
from app.routers.deps import TEST_USER_ID, get_current_user

CLIENT_ID = "5b6048a2-e8ae-4892-85c5-07f1ec9b6225"
CONSUMERS_ISSUER = "https://login.microsoftonline.com/9188040d-6c67-4c5b-b112-36a304b66dad/v2.0"


def _settings(auth_enabled: bool, allowed_user_ids: list[str] | None = None) -> Settings:
    return Settings(
        auth_enabled=auth_enabled,
        aad_tenant_id="consumers",
        aad_client_id=CLIENT_ID,
        allowed_user_ids=allowed_user_ids or [],
    )


async def _user_for_token_oid(oid: str, allowed_user_ids: list[str]) -> str:
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid-token")
    with patch("jwt.PyJWKClient") as mock_jwks_client_cls, patch("jwt.decode") as mock_decode:
        mock_jwks_client_cls.return_value.get_signing_key_from_jwt.return_value.key = "fake-key"
        mock_decode.return_value = {"oid": oid, "iss": CONSUMERS_ISSUER, "aud": CLIENT_ID}
        return await get_current_user(
            request=MagicMock(), credentials=creds, settings=_settings(True, allowed_user_ids)
        )


@pytest.mark.asyncio
async def test_allowlist_accepts_listed_account():
    assert await _user_for_token_oid("owner-oid", ["owner-oid"]) == "owner-oid"


@pytest.mark.asyncio
async def test_allowlist_rejects_other_account_with_403():
    with pytest.raises(HTTPException) as exc_info:
        await _user_for_token_oid("stranger-oid", ["owner-oid"])
    assert exc_info.value.status_code == 403


def test_allowed_user_ids_parses_json_and_comma_separated(monkeypatch):
    monkeypatch.setenv("ALLOWED_USER_IDS", '["a", "b"]')
    assert Settings().allowed_user_ids == ["a", "b"]
    assert Settings(allowed_user_ids="a, b").allowed_user_ids == ["a", "b"]


@pytest.mark.asyncio
async def test_auth_disabled_returns_test_user():
    user_id = await get_current_user(request=MagicMock(), credentials=None, settings=_settings(False))
    assert user_id == TEST_USER_ID


@pytest.mark.asyncio
async def test_auth_enabled_missing_credentials_raises_401():
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request=MagicMock(), credentials=None, settings=_settings(True))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_auth_enabled_invalid_token_raises_401():
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="garbage-token")
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request=MagicMock(), credentials=creds, settings=_settings(True))
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_auth_enabled_valid_token_returns_oid():
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid-token")

    with patch("jwt.PyJWKClient") as mock_jwks_client_cls, patch("jwt.decode") as mock_decode:
        mock_jwks_client_cls.return_value.get_signing_key_from_jwt.return_value.key = "fake-key"
        mock_decode.return_value = {
            "oid": "user-oid-123",
            "iss": CONSUMERS_ISSUER,
            "aud": CLIENT_ID,
        }

        user_id = await get_current_user(request=MagicMock(), credentials=creds, settings=_settings(True))

    assert user_id == "user-oid-123"
    # Audience + issuer must be validated against the MSA consumers tenant
    _, kwargs = mock_decode.call_args
    assert kwargs["audience"] == CLIENT_ID
    assert kwargs["issuer"] == CONSUMERS_ISSUER


@pytest.mark.asyncio
async def test_auth_enabled_token_missing_identifier_raises_401():
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid-token")

    with patch("jwt.PyJWKClient") as mock_jwks_client_cls, patch("jwt.decode") as mock_decode:
        mock_jwks_client_cls.return_value.get_signing_key_from_jwt.return_value.key = "fake-key"
        mock_decode.return_value = {"iss": CONSUMERS_ISSUER, "aud": CLIENT_ID}

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(request=MagicMock(), credentials=creds, settings=_settings(True))

    assert exc_info.value.status_code == 401
