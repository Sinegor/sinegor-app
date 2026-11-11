"""CLI failures expose safe status, never configuration values."""

from sinegor.jobs import process_destructions


def test_invalid_configuration_has_safe_nonzero_result(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["process_destructions"])

    def broken():
        raise ValueError("secret-database-value")

    monkeypatch.setattr(process_destructions, "load_settings", broken)
    assert process_destructions.main() == 1
    output = capsys.readouterr()
    assert "secret-database-value" not in output.out + output.err
    assert "documents_generation_failed" in output.out
