import pytest
from httpx import AsyncClient
from backend.core.config import settings
from backend.api.routers.auth import REFRESH_COOKIE_NAME, COOKIE_SECURE

def test_cookie_secure_config():
    """Assert COOKIE_SECURE is False in test environment (DEBUG=True)."""
    assert settings.DEBUG is True
    assert COOKIE_SECURE is False

async def test_auth_flows(app_client: AsyncClient, mock_redis):
    # 1. Register a new user
    register_payload = {
        "email": "user@example.com",
        "password": "strongpassword123",
        "risk_tolerance": "moderate"
    }
    resp = await app_client.post("/api/v1/auth/register", json=register_payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "user@example.com"
    assert "id" in data

    # 2. Register duplicate email -> 409
    resp = await app_client.post("/api/v1/auth/register", json=register_payload)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Email already registered"

    # 3. Login wrong password -> 401
    login_payload = {
        "email": "user@example.com",
        "password": "wrongpassword"
    }
    resp = await app_client.post("/api/v1/auth/login", json=login_payload)
    assert resp.status_code == 401

    # 4. Login success -> access token + cookie
    login_payload["password"] = "strongpassword123"
    resp = await app_client.post("/api/v1/auth/login", json=login_payload)
    assert resp.status_code == 200
    token_data = resp.json()
    assert "access_token" in token_data
    access_token = token_data["access_token"]

    # Verify cookie was set
    cookies = resp.cookies
    assert REFRESH_COOKIE_NAME in cookies
    refresh_token = cookies[REFRESH_COOKIE_NAME]

    # 5. Access /me with valid token
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = await app_client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200
    me_data = resp.json()
    assert me_data["email"] == "user@example.com"

    # Access /me with invalid token -> 401
    invalid_headers = {"Authorization": "Bearer badtoken"}
    resp = await app_client.get("/api/v1/auth/me", headers=invalid_headers)
    assert resp.status_code == 401

    # 6. Refresh -> new tokens
    # Pass the refresh cookie
    app_client.cookies.set(REFRESH_COOKIE_NAME, refresh_token)
    
    # Verify that without CSRF header, request is rejected with 403
    resp = await app_client.post("/api/v1/auth/refresh")
    assert resp.status_code == 403
    assert "CSRF" in resp.json()["detail"]
    
    # Verify that with CSRF header, request succeeds
    resp = await app_client.post("/api/v1/auth/refresh", headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    refresh_data = resp.json()
    assert "access_token" in refresh_data
    new_access_token = refresh_data["access_token"]
    assert new_access_token != access_token

    # Verify cookie was updated
    new_cookies = resp.cookies
    assert REFRESH_COOKIE_NAME in new_cookies

    # 7. Logout -> cookie cleared + blacklisted
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Requested-With": "XMLHttpRequest"
    }
    resp = await app_client.delete("/api/v1/auth/logout", headers=headers)
    assert resp.status_code == 200
    
    # Cookie should be cleared
    assert REFRESH_COOKIE_NAME not in resp.cookies or resp.cookies[REFRESH_COOKIE_NAME] == ""

    # Accessing /me with blacklisted token should fail with 401
    resp = await app_client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 401


async def test_login_rate_limiting(app_client: AsyncClient):
    from backend.core.limiter import limiter
    limiter._storage.reset()
    login_payload = {
        "email": "rate_limited@example.com",
        "password": "wrongpassword"
    }
    
    for _ in range(5):
        resp = await app_client.post("/api/v1/auth/login", json=login_payload)
        assert resp.status_code == 401

    resp = await app_client.post("/api/v1/auth/login", json=login_payload)
    assert resp.status_code == 429

