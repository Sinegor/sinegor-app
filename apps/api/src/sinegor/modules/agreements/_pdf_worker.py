"""Parse untrusted PDFs in a disposable Linux process with hard resource limits."""

import resource
import sys
from io import BytesIO


def main() -> int:
    try:
        # Apply limits before importing the parser or reading document bytes.
        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
        from pypdf import PdfReader
    except Exception:
        return 2
    try:
        data = sys.stdin.buffer.read(50 * 1024 * 1024 + 1)
        if len(data) > 50 * 1024 * 1024 or not data.startswith(b"%PDF-"):
            return 1
        reader = PdfReader(BytesIO(data), strict=True)
        return 0 if not reader.is_encrypted and len(reader.pages) > 0 else 1
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())
