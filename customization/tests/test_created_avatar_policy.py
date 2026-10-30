"""Creation defaults remain diverse while account pictures stay independent."""
import unittest
from unittest.mock import patch

from octop.infra.agents.settings.avatar_policy import COLORS, SHAPES, created_avatar
from octop.infra.agents.settings.geometric_avatar import avatar_response


class CreatedAvatarPolicyTests(unittest.TestCase):
    def test_all_49_combinations_are_used_before_repeating(self):
        occupied = []
        with patch("octop.infra.agents.settings.avatar_policy.secrets.choice", side_effect=lambda pool: pool[0]):
            for _ in range(49):
                selected = created_avatar({}, occupied)
                self.assertNotIn(selected, occupied)
                occupied.append(selected)
            selected = created_avatar({}, occupied)
        self.assertIn(selected["shape"], SHAPES)
        self.assertIn(selected["color"], COLORS)

    def test_explicit_preview_choice_is_preserved(self):
        config = {"avatar": {"shape": "cloud", "color": "blue"}, "memory": {"enabled": False}}
        self.assertEqual(created_avatar(config, []), config["avatar"])
        self.assertEqual(config["memory"], {"enabled": False})

    def test_legacy_null_or_invalid_shape_gets_a_valid_creation_default(self):
        for value in [None, {}, {"shape": None}, {"shape": "old-picture"}, {"shape": "cloud"}, {"shape": "cloud", "color": "old-color"}]:
            selected = created_avatar({"avatar": value}, [])
            self.assertIn(selected["shape"], SHAPES)
            self.assertIn(selected["color"], COLORS)

    def test_legacy_public_projection_is_stable_and_original_storage_is_preserved(self):
        config = {"avatar": {"shape": None}, "plugins": {"enabled": ["keep"]}}
        first = avatar_response(config, "/private-old-picture.png")
        self.assertEqual(first, avatar_response(config, "/private-old-picture.png"))
        self.assertTrue(first["icon_url"].startswith("/expert-avatars/v2/"))
        self.assertEqual(first["uploaded_icon_url"], "/private-old-picture.png")
        self.assertIsNone(config["avatar"]["shape"])
        self.assertEqual(config["plugins"], {"enabled": ["keep"]})

    def test_legacy_cache_nonce_does_not_change_the_face(self):
        first = avatar_response({}, "/old.png?v=1")
        second = avatar_response({}, "/old.png?v=2")
        self.assertEqual(first["avatar_shape"], second["avatar_shape"])
        self.assertEqual(first["avatar_color"], second["avatar_color"])
        self.assertNotEqual(first["uploaded_icon_url"], second["uploaded_icon_url"])

    def test_saved_color_is_kept_when_legacy_shape_is_missing(self):
        result = avatar_response({"avatar": {"shape": None, "color": "jade"}}, "/old.png")
        self.assertEqual(result["avatar_color"], "jade")
