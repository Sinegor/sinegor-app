"""Import this registry before using ORM mappings or Alembic metadata."""

from sinegor.modules.agreements.models import Agreement, AgreementFileDeletion
from sinegor.modules.analytics.models import AnalyticsConsentEvent
from sinegor.modules.audit.models import CustomerEvent, OrderEvent
from sinegor.modules.auth.models import AdminUser, AuthRateLimit, AuthToken, Session
from sinegor.modules.customers.models import Customer
from sinegor.modules.disk.models import DiskFolder
from sinegor.modules.notifications.models import Notification
from sinegor.modules.orders.models import MaterialHandover, Order, PaymentRecord
from sinegor.modules.retention.models import DeletionRequest, RetentionFileDeletion
from sinegor.modules.security_events.models import SecurityEvent

__all__ = [
    "AdminUser",
    "AnalyticsConsentEvent",
    "Agreement",
    "AgreementFileDeletion",
    "AuthToken",
    "AuthRateLimit",
    "Customer",
    "CustomerEvent",
    "DeletionRequest",
    "RetentionFileDeletion",
    "DiskFolder",
    "MaterialHandover",
    "Notification",
    "Order",
    "OrderEvent",
    "PaymentRecord",
    "Session",
    "SecurityEvent",
]
