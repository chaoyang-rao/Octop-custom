"""Saved reasoning follows each callee's model and its own conversation."""

import json
from types import SimpleNamespace

from octop.infra.agents.providers.reasoning import reasoning_capability
from octop.infra.agents.settings.reasoning import resolve_reasoning_overrides
from octop.infra.agents.teams.primary import request_user_id


def test_thread_and_explicit_preferences_override_only_the_selected_model():
    capability = reasoning_capability(
        {
            "id": "gpt-5.4",
            "reasoning_config": {"adapter": "openai_reasoning_effort", "efforts": ["low", "high"]},
        }
    )
    args = {
        "model_ref": "own/gpt-5.4",
        "preferences_json": json.dumps(
            {
                "model_reasoning": {
                    "host/gpt-5.4": {"mode": "disabled"},
                    "own/gpt-5.4": {"mode": "enabled", "effort": "high"},
                }
            }
        ),
    }
    assert resolve_reasoning_overrides(capability, **args) == {
        "model_fields": {"reasoning_effort": "high"}
    }
    thread = SimpleNamespace(reasoning_mode="enabled", reasoning_effort="low")
    assert resolve_reasoning_overrides(capability, **args, thread=thread) == {
        "model_fields": {"reasoning_effort": "low"}
    }
    assert resolve_reasoning_overrides(capability, **args, thread=thread, mode="disabled") == {
        "model_fields": {"reasoning_effort": "none"}
    }
    assert resolve_reasoning_overrides(None, **args) == {}


def test_standard_chat_request_identity_is_recognized_without_trusting_admin_flags():
    assert request_user_id({"user": "7"}) == 7
    assert request_user_id({"user": "7", "configurable": {"user": "8"}}) == 8
    assert request_user_id({"user": True, "user_is_admin": True}) is None
    assert request_user_id({"user": "system"}) is None
