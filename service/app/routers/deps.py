"""FastAPI shared dependencies."""
from __future__ import annotations

import structlog
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_cached_settings
from app.services.embeddings import EmbeddingService
from app.services.llm import LLMAdapter, create_llm_adapter

log = structlog.get_logger()

# Module-level singletons (initialized once)
_llm_adapter: LLMAdapter | None = None
_embedding_service: EmbeddingService | None = None

security = HTTPBearer(auto_error=False)

# Test user for AUTH_ENABLED=false
TEST_USER_ID = "test-user-local"

# Fixed tenant GUID Microsoft issues v2.0 tokens under for personal (MSA) accounts.
# The JWKS discovery endpoint accepts the "consumers" alias, but the `iss` claim in
# actual tokens always uses this resolved GUID — so issuer validation must check
# against it rather than the alias in settings.aad_tenant_id.
_MSA_CONSUMERS_TENANT_ID = "9188040d-6c67-4c5b-b112-36a304b66dad"


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    settings: Settings = Depends(get_cached_settings),
) -> str:
    """
    Authenticate and return user_id.

    When AUTH_ENABLED=false, returns a hardcoded test user.
    When AUTH_ENABLED=true, validates AAD JWT token.
    """
    if not settings.auth_enabled:
        return TEST_USER_ID

    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = credentials.credentials
    return await _validate_aad_token(token, settings)


async def _validate_aad_token(token: str, settings: Settings) -> str:
    """Validate a Microsoft identity platform JWT (MSA personal account) and return the user's oid."""
    try:
        import jwt
        from jwt import PyJWKClient

        jwks_url = (
            f"https://login.microsoftonline.com/{settings.aad_tenant_id}/discovery/v2.0/keys"
        )
        jwks_client = PyJWKClient(jwks_url, cache_keys=True)
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.aad_client_id,
            issuer=f"https://login.microsoftonline.com/{_MSA_CONSUMERS_TENANT_ID}/v2.0",
            options={"verify_exp": True, "verify_iss": True},
        )
        user_id = payload.get("oid") or payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token missing user identifier")
        return user_id

    except HTTPException:
        raise
    except Exception as e:
        log.warning("token_validation_failed", error=str(e))
        raise HTTPException(status_code=401, detail="Invalid token") from e


def get_llm_adapter(settings: Settings = Depends(get_cached_settings)) -> LLMAdapter:
    """Return the module-level LLM adapter singleton."""
    global _llm_adapter
    if _llm_adapter is None:
        _llm_adapter = create_llm_adapter(
            provider=settings.llm_provider,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            ollama_base_url=settings.ollama_base_url,
            azure_endpoint=settings.azure_openai_endpoint or None,
            azure_api_version=settings.azure_openai_api_version,
            base_url=settings.llm_base_url or None,
        )
    return _llm_adapter


def get_embedding_service(settings: Settings = Depends(get_cached_settings)) -> EmbeddingService:
    """Return the module-level embedding service singleton."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService(model_name=settings.embedding_model)
    return _embedding_service
