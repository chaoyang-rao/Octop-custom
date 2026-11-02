"""Real local signatures validate portable WebAuthn dependency compatibility.

No browser, authenticator, account secrets or network service is used. All
credential material is generated for a temporary SQLite control plane.
"""

from __future__ import annotations

import hashlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import cbor2
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.decode_credential_public_key import decode_credential_public_key
from webauthn.helpers.decoded_public_key_to_cryptography import decoded_public_key_to_cryptography
from webauthn.helpers.exceptions import InvalidCBORData
from webauthn.helpers.parse_cbor import parse_cbor
from webauthn.helpers.verify_signature import verify_signature

from octop.infra.auth.mfa import webauthn as passkeys
from octop.infra.auth.mfa.settings import SETTINGS_KEY
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.auth_challenges import AuthChallengeRepo
from octop.infra.db.repos.settings import SettingsRepo
from octop.infra.db.repos.user_webauthn import UserWebauthnRepo
from octop.infra.db.repos.users import UserRepo
from octop.infra.errors import OctopError

RP_ID = "octop.example.test"
ORIGIN = "https://octop.example.test"
CREDENTIAL_ID = b"local-software-authenticator"


def _key(algorithm):
    if algorithm == "ES256":
        private = ec.generate_private_key(ec.SECP256R1())
        public = private.public_key().public_numbers()
        cose = {1: 2, 3: -7, -1: 1, -2: public.x.to_bytes(32), -3: public.y.to_bytes(32)}

        def sign(data):
            return private.sign(data, ec.ECDSA(hashes.SHA256()))
    elif algorithm == "RS256":
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = private.public_key().public_numbers()
        cose = {1: 3, 3: -257, -1: public.n.to_bytes(256), -2: public.e.to_bytes(3)}

        def sign(data):
            return private.sign(data, padding.PKCS1v15(), hashes.SHA256())
    else:
        private = ed25519.Ed25519PrivateKey.generate()
        cose = {
            1: 1,
            3: -8,
            -1: 6,
            -2: private.public_key().public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            ),
        }
        sign = private.sign
    return cbor2.dumps(cose), sign


def _registration(repos, public_key, *, fmt="none"):
    options = passkeys.registration_options(
        settings_repo=repos.settings_repo,
        challenge_repo=repos.challenge_repo,
        webauthn_repo=repos.webauthn_repo,
        user_id=repos.user_id,
        username="compatibility-test",
        display_name=None,
        origin=ORIGIN,
    )
    client = json.dumps(
        {"type": "webauthn.create", "challenge": options["challenge"], "origin": ORIGIN}
    ).encode()
    auth = (
        hashlib.sha256(RP_ID.encode()).digest()
        + b"\x45"
        + bytes(4)
        + bytes(16)
        + len(CREDENTIAL_ID).to_bytes(2)
        + CREDENTIAL_ID
        + public_key
    )
    credential = {
        "id": bytes_to_base64url(CREDENTIAL_ID),
        "rawId": bytes_to_base64url(CREDENTIAL_ID),
        "type": "public-key",
        "response": {
            "clientDataJSON": bytes_to_base64url(client),
            "attestationObject": bytes_to_base64url(
                cbor2.dumps({"fmt": fmt, "authData": auth, "attStmt": {}})
            ),
            "transports": ["internal"],
        },
    }
    return options, credential


def _classic_passkey(case, repos, algorithm):
    public_key, sign = _key(algorithm)
    options, credential = _registration(repos, public_key)
    stored = passkeys.verify_registration(**vars(repos), credential=credential, origin=ORIGIN)
    case.assertEqual(stored.user_handle, options["user"]["id"])
    assertion = passkeys.passwordless_options(
        settings_repo=repos.settings_repo,
        challenge_repo=repos.challenge_repo,
        origin=ORIGIN,
    )
    client = json.dumps(
        {"type": "webauthn.get", "challenge": assertion["challenge"], "origin": ORIGIN}
    ).encode()
    auth = hashlib.sha256(RP_ID.encode()).digest() + b"\x05" + (1).to_bytes(4)
    credential = {
        "id": stored.credential_id,
        "rawId": stored.credential_id,
        "type": "public-key",
        "response": {
            "authenticatorData": bytes_to_base64url(auth),
            "clientDataJSON": bytes_to_base64url(client),
            "signature": bytes_to_base64url(sign(auth + hashlib.sha256(client).digest())),
            "userHandle": stored.user_handle,
        },
    }
    verification = dict(vars(repos))
    verification.pop("user_id")
    uid, checked = passkeys.verify_assertion(**verification, credential=credential, origin=ORIGIN)
    case.assertEqual(uid, repos.user_id)
    case.assertEqual(checked.credential_id, stored.credential_id)
    case.assertEqual(repos.webauthn_repo.get_by_credential_id(stored.credential_id).sign_count, 1)
    with case.assertRaises(OctopError):
        passkeys.verify_assertion(**verification, credential=credential, origin=ORIGIN)
    # A fresh challenge does not make a signature from a previous assertion valid.
    fresh = passkeys.passwordless_options(
        settings_repo=repos.settings_repo,
        challenge_repo=repos.challenge_repo,
        origin=ORIGIN,
    )
    client = json.dumps(
        {
            "type": "webauthn.get",
            "challenge": fresh["challenge"],
            "origin": ORIGIN,
        }
    ).encode()
    credential["response"]["clientDataJSON"] = bytes_to_base64url(client)
    credential["response"]["authenticatorData"] = bytes_to_base64url(auth[:-4] + (2).to_bytes(4))
    with case.assertRaises(OctopError) as altered:
        passkeys.verify_assertion(**verification, credential=credential, origin=ORIGIN)
    case.assertIn("signature", str(altered.exception.__cause__).lower())


def _algorithm_preference(case, repos):
    options, _ = _registration(repos, _key("ES256")[0])
    case.assertEqual([item["alg"] for item in options["pubKeyCredParams"]], [-8, -7, -257])


def _duplicate_cbor(case):
    # Upstream PR #285 fixture: CBOR {1: 2, true: 3} must not silently alias keys.
    with case.assertRaises(InvalidCBORData):
        parse_cbor(bytes.fromhex("a20102f503"))


def _invalid_format(case, repos, fmt):
    _, credential = _registration(repos, _key("ES256")[0], fmt=fmt)
    with case.assertRaises(OctopError) as failure:
        passkeys.verify_registration(**vars(repos), credential=credential, origin=ORIGIN)
    case.assertEqual(str(failure.exception.__cause__), "malformed attestation type")


def _pqc_signature(case, size, alg):
    from cryptography.hazmat.primitives.asymmetric import mldsa

    private = getattr(mldsa, f"MLDSA{size}PrivateKey").generate()
    encoded = cbor2.dumps(
        {
            1: 7,
            3: alg,
            -1: private.public_key().public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            ),
        }
    )
    public = decoded_public_key_to_cryptography(decode_credential_public_key(encoded))
    data = b"Local WebAuthn compatibility signature"
    signature = private.sign(data)
    verify_signature(
        public_key=public,
        signature_alg=COSEAlgorithmIdentifier(alg),
        signature=signature,
        data=data,
    )
    with case.assertRaises(InvalidSignature):
        verify_signature(
            public_key=public,
            signature_alg=COSEAlgorithmIdentifier(alg),
            signature=signature,
            data=data + b"changed",
        )


class WebAuthnCompatibilityTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="octop-webauthn-compat-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        environment = patch.dict(os.environ, {"OCTOP_HOME": str(root / "octop-home")})
        environment.start()
        self.addCleanup(environment.stop)
        pool = SqlitePool(root / "auth.db")
        self.addCleanup(pool.close)
        run_migrations(pool)
        settings = SettingsRepo(pool)
        settings.set(SETTINGS_KEY, json.dumps({"rp_id": RP_ID, "origins": [ORIGIN]}))
        uid = UserRepo(pool).create(username="compatibility-test", role="user")
        self.repos = SimpleNamespace(
            settings_repo=settings,
            challenge_repo=AuthChallengeRepo(pool),
            webauthn_repo=UserWebauthnRepo(pool),
            user_id=uid,
        )

    def test_classic_es256_registration_login_replay_and_tamper(self):
        _classic_passkey(self, self.repos, "ES256")

    def test_classic_rs256_registration_login_replay_and_tamper(self):
        _classic_passkey(self, self.repos, "RS256")

    def test_classic_eddsa_registration_login_replay_and_tamper(self):
        _classic_passkey(self, self.repos, "EDDSA")

    def test_default_algorithm_preference(self):
        _algorithm_preference(self, self.repos)

    def test_duplicate_cbor_keys_rejected(self):
        _duplicate_cbor(self)

    def test_null_attestation_format_rejected(self):
        _invalid_format(self, self.repos, None)

    def test_boolean_attestation_format_rejected(self):
        _invalid_format(self, self.repos, True)

    def test_numeric_attestation_format_rejected(self):
        _invalid_format(self, self.repos, 42)

    def test_bytes_attestation_format_rejected(self):
        _invalid_format(self, self.repos, b"none")

    def test_list_attestation_format_rejected(self):
        _invalid_format(self, self.repos, ["none"])

    def test_mldsa44_signature_and_tamper(self):
        _pqc_signature(self, 44, -48)

    def test_mldsa65_signature_and_tamper(self):
        _pqc_signature(self, 65, -49)

    def test_mldsa87_signature_and_tamper(self):
        _pqc_signature(self, 87, -50)


if __name__ == "__main__":
    unittest.main()
