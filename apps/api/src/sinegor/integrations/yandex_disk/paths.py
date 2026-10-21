"""Strict paths: never reinterpret escapes or allow deletion of an orders root."""

import unicodedata
from urllib.parse import quote


def canonical_path(value: str) -> str:
    if (
        not value.startswith("disk:/")
        or len(value) > 1024
        or any(c in value for c in ("%", "\\", "?", "#"))
        or any(unicodedata.category(c).startswith("C") for c in value)
        or unicodedata.normalize("NFC", value) != value
        or any(part in {"", ".", ".."} or part != part.strip() for part in value[6:].split("/"))
    ):
        raise ValueError("Invalid Disk path")
    return value


def child_path(path: str, root: str) -> str:
    path, root = canonical_path(path), canonical_path(root)
    if not path.startswith(root + "/"):
        raise ValueError("Disk folder must be inside the configured orders root")
    return path


def overlaps(first: str, second: str) -> bool:
    return first == second or first.startswith(second + "/") or second.startswith(first + "/")


def folder_url(path: str) -> str:
    return "https://disk.yandex.ru/client/" + "disk/" + quote(canonical_path(path)[6:], safe="/")
