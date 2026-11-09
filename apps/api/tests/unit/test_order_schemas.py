import pytest
from pydantic import ValidationError

from sinegor.modules.orders.schemas import StatusChange


def test_readiness_requires_only_confirmed_result_upload():
    change = StatusChange(status="result_ready", result_uploaded=True)
    assert change.status == "result_ready" and change.result_uploaded


@pytest.mark.parametrize("evidence", [{}, {"result_uploaded": False}])
def test_readiness_rejects_unconfirmed_result(evidence):
    with pytest.raises(ValidationError):
        StatusChange(status="result_ready", **evidence)


@pytest.mark.parametrize("status", ["in_progress", "awaiting_materials"])
def test_other_transitions_do_not_require_result_upload(status):
    change = StatusChange(status=status)
    assert change.status == status and not change.result_uploaded


def test_removed_access_confirmation_is_rejected_as_an_unknown_field():
    with pytest.raises(ValidationError) as error:
        StatusChange(status="result_ready", result_uploaded=True, access_read_only=True)
    assert error.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize("missing", [None, "", " \t\r\n", "\u00a0"])
@pytest.mark.parametrize("field", ["cancellation_internal_reason", "cancellation_customer_reason"])
def test_cancellation_requires_each_nonblank_reason(field, missing):
    reasons = {
        "cancellation_internal_reason": "Internal decision",
        "cancellation_customer_reason": "Explanation for customer",
    }
    reasons[field] = missing
    with pytest.raises(ValidationError):
        StatusChange(status="cancelled", **reasons)


def test_cancellation_strips_outer_whitespace_and_preserves_lines():
    change = StatusChange(
        status="cancelled",
        cancellation_internal_reason="  Internal\nsecond line  ",
        cancellation_customer_reason="  Customer explanation  ",
    )
    assert change.cancellation_internal_reason == "Internal\nsecond line"
    assert change.cancellation_customer_reason == "Customer explanation"


def test_reasons_cannot_be_attached_to_another_transition():
    with pytest.raises(ValidationError):
        StatusChange(status="in_progress", cancellation_internal_reason="Private")


@pytest.mark.parametrize("field", ["cancellation_internal_reason", "cancellation_customer_reason"])
def test_cancellation_reason_input_is_bounded(field):
    reasons = {
        "cancellation_internal_reason": "Internal decision",
        "cancellation_customer_reason": "Customer explanation",
    }
    reasons[field] = "x" * 10001
    with pytest.raises(ValidationError):
        StatusChange(status="cancelled", **reasons)
