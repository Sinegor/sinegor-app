import pytest
from pydantic import ValidationError

from sinegor.modules.orders.schemas import StatusChange


def test_readiness_requires_only_confirmed_result_upload():
    change = StatusChange(status="result_ready", result_uploaded=True)
    assert change.model_dump(mode="json") == {"status": "result_ready", "result_uploaded": True}


@pytest.mark.parametrize("evidence", [{}, {"result_uploaded": False}])
def test_readiness_rejects_unconfirmed_result(evidence):
    with pytest.raises(ValidationError):
        StatusChange(status="result_ready", **evidence)


@pytest.mark.parametrize("status", ["in_progress", "cancelled"])
def test_other_transitions_do_not_require_result_upload(status):
    change = StatusChange(status=status)
    assert change.model_dump(mode="json") == {"status": status, "result_uploaded": False}


def test_removed_access_confirmation_is_rejected_as_an_unknown_field():
    with pytest.raises(ValidationError) as error:
        StatusChange(status="result_ready", result_uploaded=True, access_read_only=True)
    assert error.value.errors()[0]["type"] == "extra_forbidden"
