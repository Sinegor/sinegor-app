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


def calendar_files(identifier):
    import json

    return {
        "act.pdf": b"synthetic-act",
        "journal_export.pdf": b"synthetic-export",
        "event.json": json.dumps({"operation_id": str(identifier)}).encode(),
    }


def test_calendar_archive_uses_confirmed_moscow_year_and_no_identifiers(tmp_path):
    from uuid import UUID

    store = archive(tmp_path)
    identifier = UUID(int=1)
    stamp = datetime(2026, 12, 31, 22, 32, 15, 123456, tzinfo=UTC)
    key = store.store(stamp, calendar_files(identifier), operation_id=identifier)
    assert key == "2027/2027-01-01_01-32-15"
    assert store.find_operation(stamp, identifier) == key
    assert set(p.name for p in (store.root / key).iterdir()) == {
        "act.pdf",
        "journal_export.pdf",
        "event.json",
        "manifest.json",
    }
    assert (store.root / "2027").stat().st_mode & 0o777 == 0o700
    assert (store.root / key).stat().st_mode & 0o777 == 0o700


def test_calendar_archive_collision_suffix_and_retry_after_gap(tmp_path):
    import shutil
    from uuid import UUID

    store = archive(tmp_path)
    first, second, third = (UUID(int=i) for i in (1, 2, 3))
    stamp = datetime(2026, 11, 9, 11, 32, 15, tzinfo=UTC)
    keys = [store.store(stamp, calendar_files(i), operation_id=i) for i in (first, second, third)]
    assert keys == [
        "2026/2026-11-09_14-32-15",
        "2026/2026-11-09_14-32-15_02",
        "2026/2026-11-09_14-32-15_03",
    ]
    shutil.rmtree(store.root / keys[0])
    assert store.find_operation(stamp, second) == keys[1]
    assert store.store(stamp, calendar_files(second), operation_id=second) == keys[1]
    assert len(list(store.root.rglob("manifest.json"))) == 2


def test_calendar_archive_concurrent_operations_share_second_without_duplicates(tmp_path):
    from uuid import UUID

    store = archive(tmp_path)
    stamp = datetime(2026, 11, 9, tzinfo=UTC)
    identifiers = [UUID(int=i) for i in range(1, 13)]

    def publish(identifier):
        return store.store(stamp, calendar_files(identifier), operation_id=identifier)

    with ThreadPoolExecutor(max_workers=4) as pool:
        keys = list(pool.map(publish, identifiers))
    assert len(set(keys)) == 12
    assert set(keys) == {"2026/2026-11-09_03-00-00"} | {
        f"2026/2026-11-09_03-00-00_{i:02d}" for i in range(2, 13)
    }
    assert all(
        store.find_operation(stamp, i) == key for i, key in zip(identifiers, keys, strict=True)
    )


def test_calendar_and_legacy_archives_share_backup_and_exact_retention(tmp_path):
    from uuid import UUID

    store = archive(tmp_path)
    stamp = datetime(2029, 2, 28, 12, tzinfo=UTC)
    old = store.store(stamp, calendar_files(UUID(int=1)), operation_id=UUID(int=1))
    legacy = store.store(stamp, {"act.pdf": b"legacy", "extract.pdf": b"legacy-export"})
    young = store.store(
        stamp + timedelta(microseconds=1), calendar_files(UUID(int=2)), operation_id=UUID(int=2)
    )
    refs = store.references()
    assert f"{old}/journal_export.pdf" in refs and f"{legacy}/extract.pdf" in refs
    assert len(refs) == 11
    assert store.cleanup(now=NOW, dry_run=True).removed == 2
    assert store.cleanup(now=NOW, dry_run=False).removed == 2
    assert (store.root / young / "journal_export.pdf").exists()
    assert store.read(young, "journal_export.pdf") == b"synthetic-export"


def test_calendar_archive_rejects_symlink_year_and_preserves_outside(tmp_path):
    from uuid import UUID

    store = archive(tmp_path)
    store.root.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    sentinel = outside / "keep"
    sentinel.write_bytes(b"keep")
    (store.root / "2026").symlink_to(outside, target_is_directory=True)
    stamp = datetime(2026, 11, 9, tzinfo=UTC)
    with pytest.raises(ValueError):
        store.store(stamp, calendar_files(UUID(int=1)), operation_id=UUID(int=1))
    with pytest.raises(ValueError):
        store.read("2026/2026-11-09_03-00-00", "act.pdf")
    with pytest.raises(ValueError):
        store.references()
    assert store.cleanup(now=NOW, dry_run=False).failed == 1
    assert sentinel.exists()


@pytest.mark.parametrize(
    "key",
    [
        "../2026/2026-11-09_03-00-00",
        "2026/../act.pdf",
        "/2026/2026-11-09_03-00-00",
        "2026/2027-11-09_03-00-00",
        "2026/2026-02-31_03-00-00",
        "2026/2026-11-09_03-00-00_01",
    ],
)
def test_calendar_archive_rejects_unsafe_or_invalid_keys(tmp_path, key):
    store = archive(tmp_path)
    with pytest.raises(ValueError):
        store.read(key, "act.pdf")
    with pytest.raises(ValueError):
        store.store(NOW, {"act.pdf": b"synthetic"}, key=key)


def test_calendar_archive_interrupted_publication_remains_cleanable(tmp_path, monkeypatch):
    from uuid import UUID

    store = archive(tmp_path)
    original = store._sync

    def broken(path):
        if path.name.startswith(".staging-"):
            raise OSError("synthetic")
        original(path)

    stamp = datetime(2029, 2, 28, 12, tzinfo=UTC)
    with monkeypatch.context() as patch:
        patch.setattr(store, "_sync", broken)
        with pytest.raises(OSError):
            store.store(stamp, calendar_files(UUID(int=1)), operation_id=UUID(int=1))
    assert store.find_operation(stamp, UUID(int=1)) is None
    assert store.cleanup(now=NOW, dry_run=False).removed == 1
    assert not list(store.root.rglob("act.pdf"))
