"""Pure avatar patches shared by the release builder and baseline regression tests."""

def once(text, old, new):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'Expected 1 occurrence, got {count}: {old[:120]}')
    return text.replace(old, new, 1)


def patch_main(s):
    s = 'import {createExpertAvatars} from "./expert-avatars.js";\n' + s
    s = once(s, 'function ExpertIcon({iconUrl,iconName,size=22,className}){',
        'const expertAvatarUi=createExpertAvatars({React:reactExports});function ExpertIcon(props){const generated=expertAvatarUi.parseAvatarUrl(props.iconUrl);return generated?expertAvatarUi.renderAvatar({...generated,size:Math.ceil((props.size??22)*1.2),className:props.className,style:{maxWidth:"100%",maxHeight:"100%",flexShrink:0}}):jsxRuntimeExports.jsx(LegacyExpertIcon,props)}function LegacyExpertIcon({iconUrl,iconName,size=22,className}){')
    s = once(s, 'function ExpertAgentAvatar({iconName,iconUrl,color,iconSize:iconSize2,size=32,className,muted=!1}){',
        'function ExpertAgentAvatar(props){const generated=expertAvatarUi.parseAvatarUrl(props.iconUrl);return generated?expertAvatarUi.renderAvatar({...generated,size:Math.ceil((props.size??32)*1.2),className:props.className,style:{maxWidth:"100%",maxHeight:"100%",flexShrink:0}}):jsxRuntimeExports.jsx(LegacyExpertAgentAvatar,props)}function LegacyExpertAgentAvatar({iconName,iconUrl,color,iconSize:iconSize2,size=32,className,muted=!1}){')
    s = once(s, 'icon_url:agent.icon_url,color:agent.color,is_shared:',
        'icon_url:agent.icon_url,avatar_shape:agent.avatar_shape??null,avatar_color:agent.avatar_color??null,uploaded_icon_url:agent.uploaded_icon_url??null,color:agent.color,is_shared:')
    s = once(s, 'token:{borderRadius:10,...isMobile?{fontSize:15,fontSizeSM:13,fontSizeLG:17,fontSizeXL:22,controlHeight:36}:{}',
        'token:{borderRadius:10,fontSize:13,fontSizeSM:12,fontSizeLG:15,fontSizeXL:19,...isMobile?{fontSize:14,fontSizeSM:12,fontSizeLG:16,fontSizeXL:21,controlHeight:36}:{}')
    s = once(s, 'fontSize:typeSize(14,isMobile)', 'fontSize:typeSize(13,isMobile)')
    return patch_sidebar_scrollbars(patch_navigation_avatar_sizes(s))


def patch_sidebar_scrollbars(s):
    """Mark only the two otherwise unnamed global Dock scroll containers."""
    for old in (
        'jsxRuntimeExports.jsx("div",{style:{flex:1,minHeight:0,overflowY:isMinimal&&minimalPane==="records"?"hidden":"auto",overflowX:"hidden",display:"flex",flexDirection:"column"},children:navScrollBody})',
        'jsxRuntimeExports.jsx("div",{style:{flex:1,overflow:isMinimal&&minimalPane==="records"?"hidden":"auto",minHeight:0,display:"flex",flexDirection:"column"},children:navScrollBody})',
    ):
        s = once(s, old, old.replace('{style:', '{"data-octop-sidebar-scroll":"dock",style:', 1))
    return s


def patch_navigation_avatar_sizes(s):
    """Only the three shared avatar callsites in Experts / Teams / Cloud nav.

    Each tab uses ActiveAgentCard / InactiveAgentRow in the classic rail and
    MinimalAgentSessionNav in the compact rail. Keep chat/settings sizing alone.
    """
    for old in (
        'iconUrl:agent.icon_url,iconName:agent.icon_name,size:(_a=agent.icon_url)!=null&&_a.trim()?28:16',
        'iconUrl:agent.icon_url,iconName:agent.icon_name,size:(_a=agent.icon_url)!=null&&_a.trim()?26:14',
        'iconUrl:agent.icon_url,iconName:agent.icon_name,size:(_a=agent.icon_url)!=null&&_a.trim()?22:14',
    ):
        s = once(s, old, 'iconUrl:agent.icon_url,iconName:agent.icon_name,size:48')
    return s


def patch_navigation_avatar_css(s):
    """Enlarge the actual slots, not an image hidden inside its old 22px box."""
    changes = {
        '.index-module__agentCardAvatar__vcyg9{width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0;overflow:hidden}':
        '.index-module__agentCardAvatar__vcyg9{width:48px;height:48px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0;overflow:visible}',
        '.index-module__agentRowAvatar__RwSkb{width:26px;height:26px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0;overflow:hidden}':
        '.index-module__agentRowAvatar__RwSkb{width:48px;height:48px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0;overflow:visible}',
        '.index-module__minimalAgentIconSlot__x98C5{position:relative;width:22px;height:22px;flex-shrink:0}':
        '.index-module__minimalAgentIconSlot__x98C5{position:relative;width:48px;height:48px;flex-shrink:0}',
        '.index-module__minimalAgentAvatar__M4ZP0{position:absolute;top:0;right:0;bottom:0;left:0;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;overflow:hidden;transition:opacity var(--fn-transition-fast)}':
        '.index-module__minimalAgentAvatar__M4ZP0{position:absolute;top:0;right:0;bottom:0;left:0;border-radius:6px;display:inline-flex;align-items:center;justify-content:center;overflow:visible;transition:opacity var(--fn-transition-fast)}',
        '.index-module__agentCardProfile__YJJO9{display:flex;align-items:flex-start;gap:8px;margin-bottom:4px;padding:4px 4px 2px}':
        '.index-module__agentCardProfile__YJJO9{display:flex;align-items:center;gap:8px;margin-bottom:4px;padding:4px 4px 2px}',
        '.index-module__agentRow__s5xUm{display:flex;align-items:flex-start;gap:8px;flex:1;min-width:0;padding:7px 8px;border:1px solid transparent;border-radius:10px;background:transparent;cursor:pointer;text-align:left;transition:background .15s,border-color .15s}':
        '.index-module__agentRow__s5xUm{display:flex;align-items:center;gap:8px;flex:1;min-width:0;padding:7px 8px;border:1px solid transparent;border-radius:10px;background:transparent;cursor:pointer;text-align:left;transition:background .15s,border-color .15s}',
        '.index-module__minimalAgentHeader__C9cuU{display:flex;align-items:center;gap:6px;width:100%;min-height:30px;padding-left:8px;border-radius:6px;transition:background var(--fn-transition-fast)}':
        '.index-module__minimalAgentHeader__C9cuU{display:flex;align-items:center;gap:6px;width:100%;min-height:56px;padding-left:8px;border-radius:6px;transition:background var(--fn-transition-fast)}',
    }
    for old, new in changes.items():
        s = once(s, old, new)
    return s


def patch_messages(s):
    s = 'import {createExpertAvatars} from "./expert-avatars.js";import {userBubblePresentation} from "./expert-avatar-integration.js";\n' + s
    s = once(s, 'function MessageBubble({',
        'const expertAvatarUi=createExpertAvatars({React:reactExports});function MessageBubble({')
    s = once(s, 'jsxRuntimeExports.jsxs("div",{className:chatStyles.userText,children:',
        'jsxRuntimeExports.jsxs("div",{className:chatStyles.userText,...userBubblePresentation(activeAgent,isTeamRoom,expertAvatarUi.bubbleStyle),children:')
    return s
