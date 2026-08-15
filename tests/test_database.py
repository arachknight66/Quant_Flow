import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.core.database import get_db, get_db_context

def setup_mock_session_local(monkeypatch):
    mock_session = AsyncMock()
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_session
    mock_session_local = MagicMock(return_value=mock_context)
    monkeypatch.setattr("backend.core.database.AsyncSessionLocal", mock_session_local)
    return mock_session

@pytest.mark.asyncio
async def test_get_db_commits_on_success(monkeypatch):
    mock_session = setup_mock_session_local(monkeypatch)

    generator = get_db()
    
    session = await anext(generator)
    assert session is mock_session
    
    try:
        await anext(generator)
    except StopAsyncIteration:
        pass

    assert mock_session.commit.called
    assert mock_session.close.called
    assert not mock_session.rollback.called


@pytest.mark.asyncio
async def test_get_db_rolls_back_on_exception(monkeypatch):
    mock_session = setup_mock_session_local(monkeypatch)

    generator = get_db()
    
    session = await anext(generator)
    assert session is mock_session
    
    with pytest.raises(ValueError, match="test error"):
        await generator.athrow(ValueError("test error"))

    assert mock_session.rollback.called
    assert mock_session.close.called
    assert not mock_session.commit.called


@pytest.mark.asyncio
async def test_get_db_context_standalone(monkeypatch):
    # 1. Success path
    mock_session_success = setup_mock_session_local(monkeypatch)

    async with get_db_context() as session:
        assert session is mock_session_success
        
    assert mock_session_success.commit.called
    assert mock_session_success.close.called
    assert not mock_session_success.rollback.called

    # 2. Exception path
    mock_session_fail = setup_mock_session_local(monkeypatch)

    with pytest.raises(ValueError, match="context error"):
        async with get_db_context() as session:
            assert session is mock_session_fail
            raise ValueError("context error")

    assert mock_session_fail.rollback.called
    assert mock_session_fail.close.called
    assert not mock_session_fail.commit.called
