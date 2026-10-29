"""Small pure patches layered after avatar integration; no Dock or deployment edits."""

ASSET_FILES = ("account-avatar.js", "account-avatar.css")
EXTRA_ASSETS = ASSET_FILES
STYLESHEETS = ("account-avatar.css",)
MAIN = "index.BsYGCvv_.projects-v2.js"
MESSAGES = "index.Bexwf9h5.projects-v2.js"


def once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one avatar/account patch target, got {count}: {old[:100]}")
    return text.replace(old, new, 1)


def patch_main(text: str) -> str:
    text = 'import {createAccountAvatar} from "./account-avatar.js";\n' + text
    # The factory is defined once, beside the other account components. Role
    # selectors and the profile image picker retain their existing renderer.
    text = once(text, 'function AvatarDropdown({',
                'const AccountInitialAvatar=createAccountAvatar({React:reactExports,ProfileAvatar});function AvatarDropdown({')
    text = once(text,
        'const avatar=jsxRuntimeExports.jsx(ProfileAvatar,{url:user==null?void 0:user.avatar_url,icon:user==null?void 0:user.avatar_icon,kind:"user",className:styles$h.accountAvatar},`${(user==null?void 0:user.avatar_icon)??""}:${(user==null?void 0:user.avatar_url)??""}`)',
        'const avatar=jsxRuntimeExports.jsx(AccountInitialAvatar,{user,className:styles$h.accountAvatar})')
    # Marker is placed only on generated expert SVGs, never on uploaded images
    # or the shape picker's buttons. The CSS can then clear their sole wrapper.
    marker_target = 'expertAvatarUi.renderAvatar({...generated,size:'
    if text.count(marker_target) != 2:
        raise RuntimeError("Expected the ExpertIcon and ExpertAgentAvatar generated branches")
    return text.replace(marker_target,
                        'expertAvatarUi.renderAvatar({...generated,"data-octop-geometric-avatar":"",size:')


def patch_messages(text: str) -> str:
    text = 'import {createAccountAvatar} from "./account-avatar.js";\n' + text
    text = once(text, 'function MessageSender({',
                'const AccountInitialAvatar=createAccountAvatar({React:reactExports,ProfileAvatar});function MessageSender({')
    return once(text,
        'jsxRuntimeExports.jsx(ProfileAvatar,{url:user==null?void 0:user.avatar_url,icon:user==null?void 0:user.avatar_icon,kind:"user",className:chatStyles.msgUserAvatar})',
        'jsxRuntimeExports.jsx(AccountInitialAvatar,{user,className:chatStyles.msgUserAvatar})')


def patch_sources(sources: dict[str, str]) -> dict[str, str]:
    """Accept the already avatar-patched module graph and return an updated copy."""
    out = dict(sources)
    out[MAIN] = patch_main(out[MAIN])
    out[MESSAGES] = patch_messages(out[MESSAGES])
    return out


# Explicit integration names for the release builder owned by the root agent.
patch_avatar_account_main = patch_main
patch_avatar_account_messages = patch_messages
