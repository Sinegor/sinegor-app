"""Import this registry before using ORM mappings or Alembic metadata."""

from sinegor.modules.agreements.models import Agreement
from sinegor.modules.audit.models import OrderEvent
from sinegor.modules.auth.models import AdminUser, AuthRateLimit, AuthToken, Session
from sinegor.modules.customers.models import Customer
from sinegor.modules.disk.models import DiskFolder
from sinegor.modules.orders.models import MaterialHandover, Order, PaymentRecord
from sinegor.modules.retention.models import DeletionRequest

__all__ = [
    "AdminUser",
    "Agreement",
    "AuthToken",
    "AuthRateLimit",
    "Customer",
    "DeletionRequest",
    "DiskFolder",
    "MaterialHandover",
    "Order",
    "OrderEvent",
    "PaymentRecord",
    "Session",
]
