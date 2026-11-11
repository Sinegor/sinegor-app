import pytest
from pydantic import ValidationError

from sinegor.modules.auth.schemas import CustomerCreate
from sinegor.modules.customers.schemas import CustomerUpdate


@pytest.mark.parametrize("name", [None, "", " ", "\t\r\n", "\u00a0\u2003"])
@pytest.mark.parametrize("schema", [CustomerCreate, CustomerUpdate])
def test_customer_name_rejects_empty_values(schema, name):
    with pytest.raises(ValidationError):
        schema(email="client@example.ru", display_name=name)


def test_customer_creation_requires_name():
    with pytest.raises(ValidationError):
        CustomerCreate(email="client@example.ru")


def test_partial_customer_update_keeps_omitted_fields():
    assert CustomerUpdate(phone="+7").model_dump(exclude_unset=True) == {"phone": "+7"}


@pytest.mark.parametrize("schema", [CustomerCreate, CustomerUpdate])
def test_customer_name_accepts_existing_length_limit_and_preserves_whitespace(schema):
    name = " Иван Петров "
    assert schema(email="client@example.ru", display_name=name).display_name == name
    assert schema(email="client@example.ru", display_name="я" * 255).display_name == "я" * 255
    with pytest.raises(ValidationError):
        schema(email="client@example.ru", display_name="я" * 256)


def test_customer_update_contract_allows_omission_but_not_empty_or_null_name():
    schema = CustomerUpdate.model_json_schema()
    field = schema["properties"]["display_name"]
    assert "display_name" not in schema.get("required", [])
    assert field.get("type") == "string"
    assert "anyOf" not in field
    assert field.get("minLength") == 1
    assert field["maxLength"] == 255
