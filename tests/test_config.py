import pytest
from pydantic import ValidationError
from backend.core.config import Settings

def test_secret_key_entropy_validation(monkeypatch):
    # Clear environment variable so constructor values are used
    monkeypatch.delenv("SECRET_KEY", raising=False)

    # Too short
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            SECRET_KEY="short-key",
            POSTGRES_PASSWORD="testpassword"
        )
    assert "at least 32 characters long" in str(exc_info.value)

    # Trivial key
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            SECRET_KEY="my-very-long-insecure-password-12345",
            POSTGRES_PASSWORD="testpassword"
        )
    assert "must not contain common/trivial substrings" in str(exc_info.value)

    # Valid key
    settings = Settings(
        SECRET_KEY="extremely-long-random-string-used-for-testing-purposes-only-no-trivial-patterns",
        POSTGRES_PASSWORD="testpassword"
    )
    assert settings.SECRET_KEY == "extremely-long-random-string-used-for-testing-purposes-only-no-trivial-patterns"
