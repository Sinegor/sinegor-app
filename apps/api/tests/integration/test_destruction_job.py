"""The existing periodic order job also drains documentary work without deletions."""

import pytest
from test_destruction_register import prepare

from sinegor.jobs import process_orders
from sinegor.modules.destruction import service
from sinegor.modules.retention.archive import RetentionArchive

pytestmark = pytest.mark.integration


def test_existing_periodic_job_generates_pending_pair(db_session, tmp_path, monkeypatch, capsys):
    from contextlib import nullcontext
    from types import SimpleNamespace

    op = prepare(db_session)
    service.confirm(db_session, op)
    db_session.commit()
    settings = SimpleNamespace(destruction_archive_dir=tmp_path / "archive")
    engine = SimpleNamespace(dispose=lambda: None)
    monkeypatch.setattr(process_orders, "load_settings", lambda: settings)
    monkeypatch.setattr(process_orders, "create_db_engine", lambda settings: engine)
    monkeypatch.setattr(
        process_orders, "create_session_factory", lambda engine: lambda: nullcontext(db_session)
    )
    process_orders.main()
    assert op.state == "ready"
    assert (
        RetentionArchive(settings.destruction_archive_dir)
        .read(op.bundle_key, "journal_export.pdf")
        .startswith(b"%PDF")
    )
