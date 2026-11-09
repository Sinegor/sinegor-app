from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

NOW = datetime(2032, 2, 28, 12, tzinfo=UTC)


def archive(tmp_path):
    from sinegor.modules.retention.archive import RetentionArchive

    return RetentionArchive(tmp_path / "archive")


def test_three_year_anniversary_preserves_newer_bundle_and_dry_run(tmp_path):
    store = archive(tmp_path)
    old = store.store(
        datetime(2029, 2, 28, 12, tzinfo=UTC), {"act.pdf": b"old", "export.csv": b"rows"}
    )
    young = store.store(datetime(2029, 2, 28, 12, 0, 0, 1, tzinfo=UTC), {"act.pdf": b"new"})
    assert store.cleanup(now=NOW, dry_run=True).removed == 1
    assert (store.root / old / "act.pdf").exists()
    assert store.cleanup(now=NOW, dry_run=False).removed == 1
    assert (
        not (store.root / old).exists() and (store.root / young / "act.pdf").read_bytes() == b"new"
    )
    assert store.cleanup(now=NOW, dry_run=False).removed == 0


def test_leap_day_and_unrelated_files_and_symlinks(tmp_path):
    store = archive(tmp_path)
    key = store.store(datetime(2028, 2, 29, 12, tzinfo=UTC), {"act.pdf": b"bytes"})
    (store.root / "unmanaged.pdf").write_bytes(b"keep")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "act.pdf").write_bytes(b"outside")
    (store.root / ("a" * 32)).symlink_to(outside, target_is_directory=True)
    result = store.cleanup(now=datetime(2031, 2, 28, 12, tzinfo=UTC), dry_run=False)
    assert result.removed == 1 and result.failed == 1
    assert not (store.root / key).exists() and (outside / "act.pdf").exists()
    assert (store.root / "unmanaged.pdf").exists()


def test_partial_unlink_failure_is_retryable_and_other_bundle_continues(tmp_path, monkeypatch):
    store = archive(tmp_path)
    keys = [
        store.store(NOW - timedelta(days=1200), {"act.pdf": b"act", "export.csv": b"rows"})
        for _ in range(2)
    ]
    original = Path.unlink

    def broken(path, *a, **kw):
        if path.parent.name == keys[0] and path.name == "export.csv":
            raise PermissionError("synthetic")
        return original(path, *a, **kw)

    with monkeypatch.context() as m:
        m.setattr(Path, "unlink", broken)
        result = store.cleanup(now=NOW, dry_run=False)
    assert result.failed == 1 and result.removed == 1
    assert (store.root / keys[0] / "manifest.json").exists()
    assert store.cleanup(now=NOW, dry_run=False).removed == 1


def test_archive_parallel_cleanup_and_backup_manifest(tmp_path):
    store = archive(tmp_path)
    store.store(NOW - timedelta(days=1200), {"act.pdf": b"act", "export.csv": b"rows"})
    assert len(store.references()) == 3
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: store.cleanup(now=NOW, dry_run=False), range(2)))
    assert sum(r.removed for r in results) == 1


def test_archive_invalid_time_traversal_and_corrupt_manifest_are_retained(tmp_path):
    store = archive(tmp_path)
    for when, names in [(datetime(2024, 1, 1), {"act.pdf": b"a"}), (NOW, {"../secret": b"a"})]:
        with pytest.raises(ValueError):
            store.store(when, names)
    key = store.store(NOW - timedelta(days=1200), {"act.pdf": b"act"})
    (store.root / key / "manifest.json").write_text("{bad")
    result = store.cleanup(now=NOW, dry_run=False)
    assert result.failed == 1 and (store.root / key / "act.pdf").exists()


def test_aborted_bundle_store_is_still_subject_to_retention(tmp_path, monkeypatch):
    store = archive(tmp_path)
    with monkeypatch.context() as m:
        m.setattr(store, "_sync", lambda path: (_ for _ in ()).throw(OSError("synthetic")))
        with pytest.raises(OSError):
            store.store(NOW - timedelta(days=1200), {"act.pdf": b"act"})
    assert store.cleanup(now=NOW, dry_run=False).removed == 1
    assert not list(store.root.rglob("act.pdf"))


def test_retry_after_last_manifest_unlinked_removes_empty_bundle(tmp_path, monkeypatch):
    store = archive(tmp_path)
    key = store.store(NOW - timedelta(days=1200), {"act.pdf": b"act"})
    original = Path.rmdir

    def broken(path, *args):
        if path.name == key:
            raise OSError("synthetic")
        return original(path, *args)

    with monkeypatch.context() as m:
        m.setattr(Path, "rmdir", broken)
        assert store.cleanup(now=NOW, dry_run=False).failed == 1
    assert store.cleanup(now=NOW, dry_run=False).failed == 0
    assert not (store.root / key).exists()
