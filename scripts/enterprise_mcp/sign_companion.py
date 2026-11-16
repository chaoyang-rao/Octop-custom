"""Sign a private desktop-pet component; the publisher key never leaves this host."""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from octop.infra.setup.companion import validate_archive
from octop.infra.setup.companion_package import CompanionInstaller


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.name == "posix" and (
        args.key_file.stat().st_uid != os.geteuid() or args.key_file.stat().st_mode & 0o077
    ):
        raise SystemExit("Publisher key must be private and owned by the current user")
    validate_archive(args.archive)
    with args.archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    metadata = CompanionInstaller(
        filename=args.archive.name,
        version=args.version,
        size=args.archive.stat().st_size,
        sha256=digest,
        signature="A" * 88,
    )
    key = Ed25519PrivateKey.from_private_bytes(args.key_file.read_bytes())
    metadata = metadata.model_copy(
        update={"signature": base64.b64encode(key.sign(metadata.signed_bytes())).decode()}
    )
    metadata.verify()
    args.output.write_text(metadata.model_dump_json(indent=2) + "\n")
    print(f"Signed {metadata.filename}; SHA256 {metadata.sha256}")


if __name__ == "__main__":
    main()
