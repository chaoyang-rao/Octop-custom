from octop.infra.agents.settings.geometric_avatar import (
    AVATAR_COLORS,
    avatar_response,
    is_generated_avatar_icon_url,
    validate_avatar,
)


def test_legacy_expert_avatar_projects_to_the_replacement_palette():
    old = {"avatar": {"shape": "pebble", "color": "jade"}}
    url = avatar_response(old, "private-image")["icon_url"]
    assert url == "/expert-avatars/v3/pebble-cyan.svg"
    assert old["avatar"]["color"] == "jade"
    assert is_generated_avatar_icon_url(url)
    assert is_generated_avatar_icon_url("/expert-avatars/v2/pebble-jade.svg")


def test_every_new_palette_choice_can_be_stored_and_served():
    assert len(AVATAR_COLORS) == 12
    for color in AVATAR_COLORS:
        avatar = validate_avatar({"shape": "blob", "color": color})
        assert avatar["color"] == color
        assert avatar_response({"avatar": avatar}, None)["icon_url"] == (
            f"/expert-avatars/v3/blob-{color}.svg"
        )
