"""Deletion outbox commits precede initial delivery; HTTP repeats do not retry it."""

from datetime import UTC, datetime, timedelta

import pytest
import test_disk as disk_helpers
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from test_disk import create, delete, eligible

from sinegor.integrations.email.smtp import MailDeliveryError
from sinegor.modules.disk.models import DiskFolder
from sinegor.modules.notifications import service
from sinegor.modules.notifications.models import Notification

pytestmark = pytest.mark.integration
auth = disk_helpers.auth
actors = disk_helpers.actors
admin = disk_helpers.admin


class MaterialsMailer:
    def __init__(self):
        self.messages = []
        self.fail = False

    def send_materials_deleted(self, recipient, number):
        if self.fail:
            raise MailDeliveryError("Synthetic temporary SMTP failure")
        self.messages.append((recipient, number))


@pytest.fixture
def deletion(admin, actors):
    admin.app.state.notification_mailer = MaterialsMailer()
    create(admin, actors)
    return eligible(admin, actors)


def jobs(admin):
    admin.db.expire_all()
    return list(
        admin.db.scalars(select(Notification).where(Notification.kind == "materials_deleted"))
    )


def process(admin, **kwargs):
    return service.process_pending(
        admin.db,
        admin.settings,
        auth_mailer=admin.mailer,
        order_mailer=admin.app.state.order_mailer,
        mailer=admin.app.state.notification_mailer,
        telegram=admin.app.state.telegram_notifier,
        **kwargs,
    )


def test_committed_delete_delivers_once_without_scheduler(admin, actors, deletion):
    assert delete(admin, actors, deletion).status_code == 200
    (item,) = jobs(admin)
    assert (item.status, item.attempts) == ("sent", 1)
    assert admin.app.state.notification_mailer.messages == [
        (actors.customer.email, actors.order.number)
    ]
    assert delete(admin, actors, deletion).status_code == 200
    (item,) = jobs(admin)
    assert (item.status, item.attempts) == ("sent", 1)
    assert len(admin.app.state.notification_mailer.messages) == 1
    assert process(admin) == 0


@pytest.mark.parametrize("failure", ["disk", "ineligible", "commit"])
def test_failed_deletion_never_schedules_delivery(admin, actors, deletion, monkeypatch, failure):
    if failure == "disk":
        admin.disk.fail = True
        assert delete(admin, actors, deletion).status_code == 503
    elif failure == "ineligible":
        deletion.due_at = datetime.now(UTC) + timedelta(days=1)
        admin.db.commit()
        assert delete(admin, actors, deletion).status_code == 409
    else:
        original = admin.db.commit

        def fail_final_commit():
            folder = admin.db.scalar(select(DiskFolder))
            if folder.deleted_at is not None:
                raise SQLAlchemyError("Synthetic final commit failure")
            original()

        with monkeypatch.context() as patch:
            patch.setattr(admin.db, "commit", fail_final_commit)
            assert delete(admin, actors, deletion).status_code == 500
        admin.db.rollback()
    assert jobs(admin) == []
    assert admin.app.state.notification_mailer.messages == []


def test_async_delete_only_delivers_after_verified_completion(admin, actors, deletion):
    admin.disk.pending = True
    for _ in range(2):
        assert delete(admin, actors, deletion).status_code == 202
        assert jobs(admin) == []
        assert admin.app.state.notification_mailer.messages == []
    admin.disk.status = "success"
    assert delete(admin, actors, deletion).status_code == 200
    (item,) = jobs(admin)
    assert (item.status, item.attempts) == ("sent", 1)


def test_failed_initial_delivery_waits_for_scheduler_not_repeated_http(admin, actors, deletion):
    admin.app.state.notification_mailer.fail = True
    assert delete(admin, actors, deletion).status_code == 200
    (item,) = jobs(admin)
    assert (item.status, item.attempts) == ("pending", 1)
    admin.app.state.notification_mailer.fail = False
    assert delete(admin, actors, deletion).status_code == 200
    (item,) = jobs(admin)
    assert (item.status, item.attempts) == ("pending", 1)
    assert process(admin, now=item.available_at + timedelta(seconds=1)) == 1
    (item,) = jobs(admin)
    assert (item.status, item.attempts) == ("sent", 2)
    assert len(admin.app.state.notification_mailer.messages) == 1


def test_lost_initial_background_task_is_picked_up_by_scheduler(
    admin, actors, deletion, monkeypatch
):
    from fastapi import BackgroundTasks

    # Simulate process loss after the HTTP domain commit, before task execution.
    with monkeypatch.context() as patch:
        patch.setattr(BackgroundTasks, "add_task", lambda *args, **kwargs: None)
        assert delete(admin, actors, deletion).status_code == 200
    (item,) = jobs(admin)
    assert (item.status, item.attempts) == ("pending", 0)
    assert process(admin) == 1
    (item,) = jobs(admin)
    assert (item.status, item.attempts) == ("sent", 1)
