from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sinegor.db.session import get_session


def session_request():
    session = MagicMock()
    session.__enter__.return_value = session
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                session_factory=MagicMock(return_value=session),
            )
        )
    )
    return request, session


def test_request_session_closed_without_implicit_commit():
    request, session = session_request()
    generator = get_session(request)
    assert next(generator) is session
    with pytest.raises(StopIteration):
        next(generator)
    session.__exit__.assert_called_once()
    session.commit.assert_not_called()


def test_request_session_rolls_back_and_closes_after_error():
    request, session = session_request()
    generator = get_session(request)
    next(generator)
    with pytest.raises(RuntimeError, match="failed operation"):
        generator.throw(RuntimeError("failed operation"))
    session.rollback.assert_called_once()
    session.__exit__.assert_called_once()
    session.commit.assert_not_called()
