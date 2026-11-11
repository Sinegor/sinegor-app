"""Minimal immutable identity snapshots shared by business deletion operations."""

from sinegor.modules.customers.models import Customer


def customer_metadata(
    customer: Customer,
    *,
    categories: list[str],
    entity: dict[str, str],
    source: str,
    basis: str | None,
    method: str,
    initiator: str,
    executor: str,
) -> dict:
    named = bool(customer.display_name and customer.display_name.strip())
    return {
        "subjects": [
            {
                "identity": customer.display_name if named else customer.email,
                "categories": categories,
                "source": "customers.display_name" if named else "customers.email",
            }
        ],
        "entity": entity,
        "source": source,
        "basis": basis,
        "method": method,
        "initiator": initiator,
        "executor": executor,
    }
