"""Interactive operator-only bootstrap; secrets are never CLI arguments."""

import argparse
import getpass
import sys

import pyotp
from sqlalchemy.exc import IntegrityError

from sinegor.core.config import load_settings
from sinegor.db import models  # noqa: F401 -- register relationships in this standalone CLI
from sinegor.db.session import create_db_engine, create_session_factory
from sinegor.modules.auth.service import provision_admin


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a SINEGOR administrator with TOTP")
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    settings = load_settings()
    if settings.auth_encryption_key is None:
        parser.error("Configure AUTH_ENCRYPTION_KEY first")
    password = getpass.getpass("Password (12–128 characters): ")
    if password != getpass.getpass("Repeat password: "):
        parser.error("Passwords do not match")
    if not 12 <= len(password) <= 128:
        parser.error("Password must contain 12 to 128 characters")
    secret = pyotp.random_base32()
    # Deliberately displayed once to the operator's local terminal for enrollment.
    print("Add this URI to your authenticator (keep it private):", file=sys.stderr)
    print(
        pyotp.TOTP(secret).provisioning_uri(name=args.email, issuer_name="SINEGOR"), file=sys.stderr
    )
    code = getpass.getpass("Current authenticator code: ")
    engine = create_db_engine(settings)
    try:
        with create_session_factory(engine)() as db:
            try:
                provision_admin(db, settings, args.email, password, secret, code)
            except IntegrityError:
                db.rollback()
                parser.error("Administrator already exists")
            except ValueError:
                db.rollback()
                parser.error("Invalid email, password or authenticator code")
    finally:
        engine.dispose()
    print("Administrator created. Use the next authenticator code to sign in.")


if __name__ == "__main__":
    main()
