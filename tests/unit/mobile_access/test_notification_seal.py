"""Cross-language golden vector and authenticated routing/age invariants."""

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag
from tests.unit.mobile_access.test_mobile_access_service import paired
from tests.unit.mobile_access.test_mobile_access_service import service as service

from octop.infra.errors import OctopError
from octop.infra.mobile_access.seal import (
    AAD_FIELDS,
    envelope_aad,
    notification_key,
    open_notification,
    seal_notification,
)


def vector():
    return json.loads(
        (
            Path(__file__).resolve().parents[3] / "clients/mobile/protocol/notification-vector.json"
        ).read_text()
    )


def test_python_matches_shared_hkdf_aad_and_plaintext_vector():
    value = vector()
    envelope = value["envelope"]
    key = notification_key(hashlib.sha256(value["credential"].encode()).hexdigest())
    assert base64.b64encode(key).decode() == value["notification_key_base64"]
    assert base64.b64encode(envelope_aad(envelope)).decode() == value["aad_base64"]
    result = open_notification(
        key,
        envelope,
        host=envelope["host_fingerprint"],
        device=envelope["device_id"],
        now=value["now"],
    )
    assert result == value["expected_payload"]


@pytest.mark.parametrize("field", list(AAD_FIELDS))
def test_all_authenticated_context_fields_reject_substitution(field):
    value = vector()
    envelope = dict(value["envelope"])
    key = notification_key(hashlib.sha256(value["credential"].encode()).hexdigest())
    envelope[field] = "tampered"
    with pytest.raises((ValueError, InvalidTag)):
        open_notification(
            key,
            envelope,
            host=value["envelope"]["host_fingerprint"],
            device=value["envelope"]["device_id"],
            now=value["now"],
        )


def test_exact_replay_expiry_future_and_recipient_are_rejected():
    value = vector()
    envelope = value["envelope"]
    key = notification_key(hashlib.sha256(value["credential"].encode()).hexdigest())
    options = {
        "host": envelope["host_fingerprint"],
        "device": envelope["device_id"],
        "now": value["now"],
    }
    seen = set()
    open_notification(key, envelope, **options, seen=seen)
    with pytest.raises(ValueError, match="replay"):
        open_notification(key, envelope, **options, seen=seen)
    for changed in [
        {"now": value["now"] + 300},
        {"now": value["now"] - 61},
        {"device": "wrong"},
        {"host": "wrong"},
    ]:
        with pytest.raises(ValueError):
            open_notification(key, envelope, **(options | changed))


def test_random_nonce_is_independent_for_identical_messages():
    value = vector()
    envelope = value["envelope"]
    key = notification_key(hashlib.sha256(value["credential"].encode()).hexdigest())
    first = seal_notification(
        key,
        host=envelope["host_fingerprint"],
        device=envelope["device_id"],
        payload=value["expected_payload"],
    )
    second = seal_notification(
        key,
        host=envelope["host_fingerprint"],
        device=envelope["device_id"],
        payload=value["expected_payload"],
    )
    assert (
        base64.urlsafe_b64decode(first["sealed"])[:12]
        != base64.urlsafe_b64decode(second["sealed"])[:12]
    )
    assert first["message_id"] != second["message_id"]


@pytest.mark.asyncio
async def test_message_key_is_not_usable_as_a_device_login(service):
    _, result = await paired(service)
    key = notification_key(hashlib.sha256(result["access_token"].encode()).hexdigest())
    forged = result["access_token"].rsplit(".", 1)[0] + "." + base64.urlsafe_b64encode(key).decode()
    with pytest.raises(OctopError):
        service.authenticate(forged)
