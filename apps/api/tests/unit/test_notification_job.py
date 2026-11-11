"""CLI failures must be visible without printing connection details or SQL values."""

import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from sinegor.jobs import process_notifications as job


def test_configuration_failure_has_nonzero_result_and_safe_log(monkeypatch, capsys):
    def fail():
        raise ValueError("private-database-password-and-address")

    monkeypatch.setattr(job, "load_settings", fail)
    assert job.main() == 1
    output = capsys.readouterr()
    assert "private-database-password-and-address" not in output.out + output.err
    entries = [json.loads(line) for line in output.out.splitlines()]
    assert entries[-1]["event"] == "notifications_run_failed"
    assert entries[-1]["exception_type"] == "ValueError"


@pytest.mark.parametrize("failure", [None, "database", "dispose"])
def test_run_records_result_and_releases_engine(monkeypatch, capsys, failure):
    class Engine:
        disposed = False

        def dispose(self):
            self.disposed = True
            if failure == "dispose":
                raise RuntimeError("private-connection-details")

    engine = Engine()
    monkeypatch.setattr(job, "load_settings", lambda: SimpleNamespace(log_level="WARNING"))
    monkeypatch.setattr(job, "create_db_engine", lambda settings: engine)
    monkeypatch.setattr(job, "create_session_factory", lambda engine: lambda: nullcontext(None))
    monkeypatch.setattr(job, "SMTPAuthMailer", lambda settings: None)
    monkeypatch.setattr(job, "TelegramNotifier", lambda settings: None)
    monkeypatch.setattr(job, "queue_deletion_reminders", lambda db: None)

    def process(*args, **kwargs):
        if failure == "database":
            raise RuntimeError("private-connection-details")
        return 3

    monkeypatch.setattr(job, "process_pending", process)
    assert job.main() == (0 if failure is None else 1)
    assert engine.disposed
    output = capsys.readouterr()
    assert "private-connection-details" not in output.out + output.err
    records = [json.loads(line) for line in output.out.splitlines()]
    if failure is None:
        assert records[-1]["event"] == "notifications_run_completed delivered=3"
        assert records[-1]["duration_ms"] >= 0
    else:
        assert records[-1]["event"] == "notifications_run_failed"
        assert records[-1]["exception_type"] == "RuntimeError"
