import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from tests.unit.enterprise_resources.test_resources import definition, publish

from octop.api.deps import current_user, get_server
from octop.api.routers.enterprise_resources_admin import router
from octop.infra.enterprise_resources.models import ResourceAudience
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.mobile_access.access import MobileUser


def audience(company, user):
    return ResourceAudience(
        scope="selected", subjects=[company.catalog.center.require_employee(user)]
    )


@pytest.mark.parametrize("kind", ["expert", "skill"])
def test_assignment_updates_only_published_scope_and_retains_every_content_draft(company, kind):
    state = publish(company, definition(kind), definition(resource_id="untouched"))
    published = {entry.resource_id: entry for entry in state.published.entries}
    target_file = "SOUL.md" if kind == "expert" else "SKILL.md"
    state = company.catalog.save_entry(
        company.admin, definition(kind, files={target_file: b"unpublished target v2"}), state.etag
    )
    state = company.catalog.save_entry(
        company.admin,
        definition(resource_id="untouched", files={"SOUL.md": b"unpublished other v2"}),
        state.etag,
    )
    drafts = {entry.resource_id: entry.digest for entry in state.draft}
    selected = audience(company, company.alice)
    updated = company.catalog.assign(company.admin, "quality", selected, state.etag)
    assert updated.published.revision == state.published.revision + 1
    assert {entry.resource_id: entry.digest for entry in updated.draft} == drafts
    assert {entry.resource_id: entry.digest for entry in updated.published.entries} == {
        key: entry.digest for key, entry in published.items()
    }
    assert (
        next(e for e in updated.draft if e.resource_id == "quality").allowed_subjects
        == selected.subjects
    )
    assert (
        next(e for e in updated.published.entries if e.resource_id == "quality").allowed_subjects
        == selected.subjects
    )
    assert {e.resource_id for e in company.catalog.member(company.alice).entries} == {
        "quality",
        "untouched",
    }
    assert {e.resource_id for e in company.catalog.member(company.bob).entries} == {"untouched"}
    with pytest.raises(OctopError):
        company.catalog.bundle(company.bob, published["quality"].digest)
    restored = company.catalog.assign(
        company.admin, "quality", ResourceAudience(scope="all"), updated.etag
    )
    assert {e.resource_id for e in company.catalog.member(company.bob).entries} == {
        "quality",
        "untouched",
    }
    assert {e.resource_id: e.digest for e in restored.draft} == drafts


def test_unpublished_assignment_stays_a_draft_and_unknown_or_stale_requests_do_not_change_it(
    company,
):
    state = company.catalog.save_entry(
        company.admin, definition(), company.catalog.admin(company.admin).etag
    )
    state = company.catalog.assign(
        company.admin, "quality", audience(company, company.alice), state.etag
    )
    assert state.published.revision == 0
    assert not company.catalog.member(company.alice).entries
    with pytest.raises(OctopError) as error:
        company.catalog.assign(
            company.admin,
            "quality",
            ResourceAudience(scope="selected", subjects=["unknown"]),
            state.etag,
        )
    assert error.value.code == ErrorCode.ENTERPRISE_RESOURCE_INVALID
    assert company.catalog.admin(company.admin).etag == state.etag
    changed = company.catalog.save_entry(company.admin, definition(resource_id="other"), state.etag)
    with pytest.raises(OctopError) as error:
        company.catalog.assign(company.admin, "quality", ResourceAudience(scope="all"), state.etag)
    assert error.value.code == ErrorCode.ENTERPRISE_RESOURCE_CONFLICT
    assert company.catalog.admin(company.admin).etag == changed.etag


@pytest.mark.parametrize(
    "scope,subjects", [("selected", []), ("all", ["member"]), ("selected", ["bad subject"])]
)
def test_assignment_requires_an_explicit_nonempty_selection(scope, subjects):
    with pytest.raises(ValidationError):
        ResourceAudience(scope=scope, subjects=subjects)


@pytest.mark.parametrize("resource_id,all_members", [("quality", True), ("skill", False)])
def test_assignment_preserves_expert_skill_visibility_dependencies(
    company, resource_id, all_members
):
    subject = audience(company, company.alice).subjects
    state = publish(
        company,
        definition("skill", "skill", allowed_subjects=subject),
        definition(skill_refs=["skill"], allowed_subjects=subject),
    )
    selected = ResourceAudience(scope="all") if all_members else audience(company, company.bob)
    with pytest.raises(OctopError):
        company.catalog.assign(company.admin, resource_id, selected, state.etag)
    assert company.catalog.admin(company.admin).etag == state.etag


async def test_assignment_revokes_distribution_without_deleting_existing_member_copies(company):
    publish(company, definition())
    for node in company.nodes:
        await node.sync.sync(node.user)
    bob = company.nodes[1]
    before = bob.sync._state(bob.user.id)["resources"]["quality"]["target_id"]
    state = company.catalog.admin(company.admin)
    company.catalog.assign(company.admin, "quality", audience(company, company.alice), state.etag)
    await bob.sync.sync(bob.user)
    assert not any(e["enabled"] for e in bob.sync.status(bob.user)["resources"])
    assert bob.server.services.agent_repo.get(before) is not None
    assert bob.registry.workspaces[before].files["USER.md"] == b"personal preferences"
    assert bob.registry.workspaces[before].files["memory/private.md"] == b"private memory"


async def test_assignment_http_validates_scope_and_rejects_members_and_device_administrators(
    company,
):
    state = publish(company, definition())
    app = FastAPI()
    app.include_router(router, prefix="/api")
    actor = {"user": company.admin}
    app.dependency_overrides[current_user] = lambda: actor["user"]
    app.dependency_overrides[get_server] = lambda: company.center

    @app.exception_handler(OctopError)
    async def failure(request, error):
        return JSONResponse(error.to_envelope(), status_code=error.status)

    body = {
        "resource_id": "quality",
        "expected_etag": state.etag,
        "audience": audience(company, company.alice).model_dump(),
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://company.example"
    ) as client:
        for denied in [
            company.alice,
            MobileUser(**company.admin.__dict__, device_id="node", device_scopes=("enterprise",)),
        ]:
            actor["user"] = denied
            response = await client.put("/api/enterprise/resources/admin/assignment", json=body)
            assert response.status_code == 403
        actor["user"] = company.admin
        response = await client.put(
            "/api/enterprise/resources/admin/assignment",
            json={
                **body,
                "audience": {"scope": "selected", "subjects": []},
                "password": "do-not-echo",
            },
        )
        assert response.status_code == 400 and "do-not-echo" not in response.text
        response = await client.put("/api/enterprise/resources/admin/assignment", json=body)
    assert response.status_code == 200
    assert (
        response.json()["published"]["entries"][0]["allowed_subjects"]
        == body["audience"]["subjects"]
    )
    assert "files" not in json.dumps(response.json())
