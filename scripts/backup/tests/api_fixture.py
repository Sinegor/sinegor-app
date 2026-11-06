"""Synthetic records for the isolated restore smoke test; never uses project dotenv."""

import hashlib
import io
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pypdf import PdfWriter
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(os.environ["SINEGOR_BACKUP_PROJECT"]) / "apps/api/src"))
from sinegor.db import models  # noqa: E402, F401
from sinegor.db.types import ServiceType  # noqa: E402
from sinegor.modules.agreements.models import Agreement, AgreementFileDeletion  # noqa: E402
from sinegor.modules.agreements.storage import AgreementStorage  # noqa: E402
from sinegor.modules.auth.models import AdminUser  # noqa: E402
from sinegor.modules.customers.models import Customer  # noqa: E402
from sinegor.modules.orders.models import Order  # noqa: E402


def main():
    private = Path(os.environ["SINEGOR_BACKUP_PRIVATE"])
    root = Path(os.environ["AGREEMENT_STORAGE_DIR"])
    engine = create_engine(os.environ["DATABASE_URL"], hide_parameters=True)
    try:
        with Session(engine) as db:
            if sys.argv[1] == "seed":
                writer, stream = PdfWriter(), io.BytesIO()
                writer.add_blank_page(width=200, height=200)
                writer.write(stream)
                data = stream.getvalue()
                (private / "synthetic.pdf").write_bytes(data)
                storage = AgreementStorage(root)
                final, digest = storage.put(data)
                initial, _ = storage.put(data)
                obsolete, _ = storage.put(data)
                customer = Customer(email="restore-fixture@example.org")
                admin = AdminUser(email="restore-admin@example.org", password_hash="synthetic")
                db.add_all([customer, admin])
                db.flush()
                now = datetime.now(UTC)
                orders = [
                    Order(customer_id=customer.id, service_type=ServiceType.ANALYSIS)
                    for _ in range(2)
                ]
                db.add_all(orders)
                db.flush()
                db.add_all(
                    [
                        Agreement(
                            order_id=orders[0].id,
                            status="approved",
                            final_pdf_key=final,
                            final_sha256=digest,
                            verified_by_id=admin.id,
                            verified_at=now,
                            created_at=now - timedelta(seconds=1),
                        ),
                        Agreement(
                            order_id=orders[1].id, initial_pdf_key=initial, initial_sha256=digest
                        ),
                        AgreementFileDeletion(order_id=orders[0].id, file_key=obsolete),
                    ]
                )
                db.commit()
                (private / "api-expected.json").write_text(
                    json.dumps(
                        {
                            "final": final,
                            "initial": initial,
                            "obsolete": obsolete,
                            "digest": digest,
                        }
                    )
                )
            else:
                expected = json.loads((private / "api-expected.json").read_text())
                rows = db.scalars(select(Agreement)).all()
                assert len(rows) == 2
                approved = next(row for row in rows if row.final_pdf_key)
                assert approved.final_pdf_key == expected["final"]
                assert approved.final_sha256 == expected["digest"]
                for key in (expected["final"], expected["initial"]):
                    data = (root / key).read_bytes()
                    assert data == (private / "synthetic.pdf").read_bytes()
                    assert hashlib.sha256(data).hexdigest() == expected["digest"]
                assert (root / expected["obsolete"]).exists() == (sys.argv[1] == "verify-source")
                assert db.scalar(select(models.Customer.email)) == "restore-fixture@example.org"
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
