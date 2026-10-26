import pytest
from pydantic import ValidationError

from sinegor.modules.auth.schemas import EmailInput
from sinegor.modules.notifications.schemas import ConsultationInput


@pytest.mark.parametrize(
    ("phone", "normalized"),
    [
        ("+7 (999) 123-45-67", "+79991234567"),
        (" +44 20 7946 0958 ", "+442079460958"),
        ("+1234567", "+1234567"),
        ("+123456789012345", "+123456789012345"),
        ("+1234567" + " " * 42, "+1234567"),
    ],
)
def test_consultation_normalizes_contacts(phone, normalized):
    payload = ConsultationInput(email=" Person@Example.ru ", phone=phone)
    assert payload.model_dump() == {"email": "person@example.ru", "phone": normalized}


@pytest.mark.parametrize(
    "phone",
    [
        None,
        79991234567,
        "",
        " ",
        "89991234567",
        "+0123456789",
        "+123456",
        "+1234567890123456",
        "+1234567" + " " * 43,
        "+7 (999) CALL-NOW",
        "+79991234567 ext 1",
        "+79991234567\nEmail: attacker@example.ru",
        "+79991234567\n",
        "\t+79991234567",
        "+7999\r1234567",
        "+7999\t1234567",
        "+٧٩٩٩١٢٣٤٥٦٧",
        "+7999\u00a01234567",
        "++79991234567",
        "+7<script>9991234567",
    ],
)
def test_consultation_rejects_invalid_phone(phone):
    with pytest.raises(ValidationError):
        ConsultationInput(email="person@example.ru", phone=phone)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"email": "person@example.ru"},
        {"phone": "+79991234567"},
        {"email": "bad", "phone": "+79991234567"},
        {"email": "person@example.ru", "phone": "+79991234567", "files": []},
    ],
)
def test_consultation_requires_both_contacts_and_forbids_extra_fields(payload):
    with pytest.raises(ValidationError):
        ConsultationInput.model_validate(payload)


def test_email_only_input_remains_unchanged_for_other_flows():
    assert EmailInput(email=" Person@Example.ru ").email == "person@example.ru"
    with pytest.raises(ValidationError):
        EmailInput(email="person@example.ru", phone="+79991234567")
