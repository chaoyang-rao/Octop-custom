/** Pure rendering patch; the existing model menu and callbacks stay authoritative. */
function once(source, before, after) {
  const count = source.split(before).length - 1;
  if (count !== 1) throw new Error(`Model shortcut patch expected one anchor, found ${count}: ${before.slice(0, 90)}`);
  return source.replace(before, after);
}

export function patchComposerModelShortcut(source) {
  const start = source.indexOf('function ChatInputActionsRow(');
  const end = source.indexOf('function previewText(', start);
  if (start < 0 || end <= start) throw new Error('ChatInputActionsRow boundary changed');
  let block = source.slice(start, end);
  if (block.includes('composer-model-shortcut')) throw new Error('Model shortcut was already patched');
  block = once(block, 'availableModels,selectedModel,onModelChange,reasoningMode=',
    'availableModels,selectedModel,defaultModel,onModelChange,reasoningMode=');
  block = once(block, '[reasoningModelRef,setReasoningModelRef]=reactExports.useState(null),handleVoicePressStart=',
    '[reasoningModelRef,setReasoningModelRef]=reactExports.useState(null),[modelShortcutOpen,setModelShortcutOpen]=reactExports.useState(!1),handleVoicePressStart=');
  block = once(block, 'const showModelPicker=!!(availableModels&&availableModels.length>0&&onModelChange),allowWriteTools=',
    'const showModelPicker=!!(availableModels&&availableModels.length>0&&onModelChange);reactExports.useEffect(()=>{(disabled||!showModelPicker)&&setModelShortcutOpen(!1)},[disabled,showModelPicker]);const allowWriteTools=');
  block = once(block, 'closePlusMenu=()=>{setOverflowPopoverOpen(!1),closeCompactPicker()}',
    'closePlusMenu=()=>{setModelShortcutOpen(!1),setOverflowPopoverOpen(!1),closeCompactPicker()}');
  block = once(block, ':t("chat.modelAuto","Auto"),modelQueryNormalized=',
    ':t("chat.modelAuto","Auto"),shortcutModelRef=selectedModel||defaultModel,shortcutModel=availableModels==null?void 0:availableModels.find(model=>modelOptionValue(model)===shortcutModelRef),modelShortcutLabel=(shortcutModel==null?void 0:shortcutModel.name)||modelShortLabel((shortcutModel==null?void 0:shortcutModel.model)||shortcutModelRef||"")||t("chat.modelAuto","Auto"),modelShortcutTitle=shortcutModelRef?`${selectedModel?"":`${t("chat.modelAuto","Auto")} · `}${shortcutModel?modelOptionLabel(shortcutModel):shortcutModelRef}`:selectedModelTriggerLabel,modelQueryNormalized=');
  block = once(block, 'onOpenChange:open=>{setOverflowPopoverOpen(open),open||closeCompactPicker()}',
    'onOpenChange:open=>{open&&setModelShortcutOpen(!1),setOverflowPopoverOpen(open),open||closeCompactPicker()}');
  const shortcut = 'showModelPicker&&jsxRuntimeExports.jsx(Popover,{trigger:"click",placement:"topLeft",arrow:!1,destroyOnHidden:!0,open:modelShortcutOpen,overlayClassName:`${chatStyles.modelPopover} octop-model-shortcut-popover`,content:jsxRuntimeExports.jsx("div",{role:"dialog","aria-label":t("chat.selectModel","Model"),children:modelMenu}),onOpenChange:open=>{disabled||(setModelShortcutOpen(open),open&&(setOverflowPopoverOpen(!1),closeCompactPicker()))},children:jsxRuntimeExports.jsx(Tooltip,{title:modelShortcutTitle,mouseEnterDelay:.4,children:jsxRuntimeExports.jsxs("button",{type:"button",className:"octop-model-shortcut","data-testid":"composer-model-shortcut","data-compact":useCompactControls,disabled,"aria-haspopup":"dialog","aria-expanded":modelShortcutOpen,"aria-label":`${t("chat.selectModel","Model")}: ${modelShortcutTitle}`,children:[jsxRuntimeExports.jsx(Cpu,{size:16,"aria-hidden":!0}),jsxRuntimeExports.jsx("span",{children:modelShortcutLabel}),jsxRuntimeExports.jsx(ChevronRight,{size:12,className:"octop-model-shortcut-chevron","aria-hidden":!0})]})})})';
  block = once(block, 'className:chatStyles.secondaryActions,children:renderSecondaryActions()}),conversationMode',
    `className:chatStyles.secondaryActions,children:renderSecondaryActions()}),${shortcut},conversationMode`);
  return source.slice(0, start) + block + source.slice(end);
}
