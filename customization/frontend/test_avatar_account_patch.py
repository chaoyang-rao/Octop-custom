"""Verify pure avatar/account patches against the existing v3 graph, without writing it."""
from pathlib import Path
import shutil
import subprocess
import unittest

from avatar_account_patch import patch_avatar_account_main, patch_avatar_account_messages

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "packages" / "octop" / "dashboard" / "assets"


class AvatarAccountPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = (ASSETS / "index.BsYGCvv_.avatars-v3.js").read_text()
        cls.messages = (ASSETS / "index.Bexwf9h5.avatars-v3.js").read_text()

    def test_only_generated_expert_branches_receive_frame_marker(self):
        patched = patch_avatar_account_main(self.main)
        self.assertEqual(patched.count('"data-octop-geometric-avatar":""'), 2)
        for name, legacy in (("ExpertIcon", "LegacyExpertIcon"), ("ExpertAgentAvatar", "LegacyExpertAgentAvatar")):
            original = self.main[self.main.index(f"function {legacy}("):]
            original = original[:original.index("}function ")+1] if "}function " in original else original
            self.assertIn(original, patched)
        self.assertIn('Math.ceil((props.size??22)*1.2)', patched)
        self.assertIn('Math.ceil((props.size??32)*1.2)', patched)
        self.assertIn('iconUrl:agent.icon_url,iconName:agent.icon_name,size:48', patched)

    def test_account_entry_changes_without_replacing_role_or_picker_avatars(self):
        patched = patch_avatar_account_main(self.main)
        self.assertIn('createAccountAvatar({React:reactExports,ProfileAvatar})', patched)
        self.assertEqual(patched.count('const avatar=jsxRuntimeExports.jsx(AccountInitialAvatar,{user,className:styles$h.accountAvatar})'), 1)
        self.assertIn('jsxRuntimeExports.jsx(ProfileAvatar,{url,icon:icon2,kind:"role"', patched)
        self.assertIn('jsxRuntimeExports.jsx(ProfileAvatar,{url:displayUrl,icon:icon2,kind,className:', patched)
        self.assertNotIn('const avatar=jsxRuntimeExports.jsx(ProfileAvatar,{url:user', patched)

    def test_user_message_scope_and_team_bubble_guard_are_preserved(self):
        patched = patch_avatar_account_messages(self.messages)
        self.assertIn('createAccountAvatar({React:reactExports,ProfileAvatar})', patched)
        self.assertEqual(patched.count('jsxRuntimeExports.jsx(AccountInitialAvatar,{user,className:chatStyles.msgUserAvatar})'), 1)
        self.assertIn('senderAvatar=(isUser||groupPosition===', patched)
        self.assertIn('isUser?jsxRuntimeExports.jsx(MessageSender,{name:userName,avatar:jsxRuntimeExports.jsx(AccountInitialAvatar', patched)
        self.assertIn('userBubblePresentation(activeAgent,isTeamRoom,expertAvatarUi.bubbleStyle)', patched)
        # The actual user text and assistant rich-text branches are unchanged.
        for needle in ('children:message2.content', 'jsxRuntimeExports.jsx(LazyMarkdown,{content:textContent'):
            self.assertEqual(self.messages.count(needle), patched.count(needle))

    def test_patch_refuses_duplicate_or_missing_targets(self):
        with self.assertRaises(RuntimeError):
            patch_avatar_account_main(self.main + self.main)
        with self.assertRaises(RuntimeError):
            patch_avatar_account_messages('unexpected upstream source')

    def test_both_patched_modules_parse(self):
        node = shutil.which("node")
        self.assertIsNotNone(node)
        for source in (patch_avatar_account_main(self.main), patch_avatar_account_messages(self.messages)):
            checked = subprocess.run([node, "--input-type=module", "--check"], input=source,
                                     text=True, capture_output=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)


if __name__ == "__main__":
    unittest.main()
