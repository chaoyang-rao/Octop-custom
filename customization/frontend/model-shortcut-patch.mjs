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
    '[reasoningModelRef,setReasoningModelRef]=reactExports.useState(null),[modelShortcutOpen,setModelShortcutOpen]=reactExports.useState(!1),[modelSlotEl,setModelSlotEl]=reactExports.useState(null),handleVoicePressStart=');
  block = once(block, 'const showModelPicker=!!(availableModels&&availableModels.length>0&&onModelChange),allowWriteTools=',
    'const showModelPicker=!!(availableModels&&availableModels.length>0&&onModelChange);reactExports.useEffect(()=>{(disabled||!showModelPicker)&&setModelShortcutOpen(!1)},[disabled,showModelPicker]);reactExports.useEffect(()=>{setModelSlotEl(document.getElementById("octop-model-slot"))},[]);const allowWriteTools=');
  block = once(block, 'closePlusMenu=()=>{setOverflowPopoverOpen(!1),closeCompactPicker()}',
    'closePlusMenu=()=>{setModelShortcutOpen(!1),setOverflowPopoverOpen(!1),closeCompactPicker()}');
  block = once(block, ':t("chat.modelAuto","Auto"),modelQueryNormalized=',
    ':t("chat.modelAuto","Auto"),shortcutModelRef=selectedModel||defaultModel,shortcutModel=availableModels==null?void 0:availableModels.find(model=>modelOptionValue(model)===shortcutModelRef),modelShortcutLabel=(shortcutModel==null?void 0:shortcutModel.name)||modelShortLabel((shortcutModel==null?void 0:shortcutModel.model)||shortcutModelRef||"")||t("chat.modelAuto","Auto"),modelShortcutTitle=shortcutModelRef?`${selectedModel?"":`${t("chat.modelAuto","Auto")} · `}${shortcutModel?modelOptionLabel(shortcutModel):shortcutModelRef}`:selectedModelTriggerLabel,modelQueryNormalized=');
  block = once(block, 'onOpenChange:open=>{setOverflowPopoverOpen(open),open||closeCompactPicker()}',
    'onOpenChange:open=>{open&&setModelShortcutOpen(!1),setOverflowPopoverOpen(open),open||closeCompactPicker()}');
  const shortcut = 'showModelPicker&&jsxRuntimeExports.jsx(Popover,{trigger:"click",placement:"topLeft",arrow:!1,destroyOnHidden:!0,open:modelShortcutOpen,overlayClassName:`${chatStyles.modelPopover} octop-model-shortcut-popover`,content:jsxRuntimeExports.jsx("div",{role:"dialog","aria-label":t("chat.selectModel","Model"),children:modelMenu}),onOpenChange:open=>{disabled||(setModelShortcutOpen(open),open&&(setOverflowPopoverOpen(!1),closeCompactPicker()))},children:jsxRuntimeExports.jsx(Tooltip,{title:modelShortcutTitle,mouseEnterDelay:.4,children:jsxRuntimeExports.jsxs("button",{type:"button",className:"octop-model-shortcut","data-testid":"composer-model-shortcut","data-compact":useCompactControls,disabled,"aria-haspopup":"dialog","aria-expanded":modelShortcutOpen,"aria-label":`${t("chat.selectModel","Model")}: ${modelShortcutTitle}`,children:[jsxRuntimeExports.jsx("span",{children:modelShortcutLabel}),jsxRuntimeExports.jsx(ChevronRight,{size:12,className:"octop-model-shortcut-chevron","aria-hidden":!0})]})})})';
  // The pill is portalled into the dedicated row that ChatInput renders under
  // the composer box; without that row (isolated component tests) it stays inline.
  const pill = shortcut.slice('showModelPicker&&'.length);
  block = once(block, 'className:chatStyles.secondaryActions,children:renderSecondaryActions()}),conversationMode',
    `className:chatStyles.secondaryActions,children:renderSecondaryActions()}),showModelPicker&&(modelSlotEl?reactDomExports.createPortal(${pill},modelSlotEl):${pill}),conversationMode`);

  // The selector no longer hides behind the "+" tools menu.
  const plusStart = block.indexOf('showModelPicker&&jsxRuntimeExports.jsxs("button"');
  const plusEnd = block.indexOf('showConnectorPicker&&jsxRuntimeExports.jsxs("button"', plusStart);
  if (plusStart < 0 || plusEnd <= plusStart) throw new Error('Plus-menu model entry boundary changed');
  if (!block.slice(plusStart, plusEnd).includes('openCompactPicker("model")')) throw new Error('Plus-menu model entry anchor changed');
  block = block.slice(0, plusStart) + block.slice(plusEnd);
  block = once(block, 'case"model":return modelMenu;', '');
  block = once(block, 'model:t("chat.selectModel","Model"),', '');
  block = once(block, 'key!=="model"&&setModelQuery("")', 'setModelQuery("")');


  let out = source.slice(0, start) + block + source.slice(end);
  // The selector shares the tool row: first child of the actions row, so it sits
  // on the same line as the tool buttons instead of taking its own row.
  out = once(out, 'children:[jsxRuntimeExports.jsx("div",{className:chatStyles.secondaryActions',
    'children:[jsxRuntimeExports.jsx("div",{id:"octop-model-slot","data-testid":"composer-model-slot",className:"octop-model-slot"}),jsxRuntimeExports.jsx("div",{className:chatStyles.secondaryActions');
  // The inline "model" chip in the preview bar is replaced by the row below.
  out = once(out, 'showModelChip=selectedModelValue.length>0&&!!onModelChange', 'showModelChip=!1');
  return out;
}
