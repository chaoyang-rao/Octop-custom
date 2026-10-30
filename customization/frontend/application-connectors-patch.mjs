import fs from "node:fs";
import { fileURLToPath } from "node:url";

function once(source, from, to) {
  const count = source.split(from).length - 1;
  if (count !== 1) throw new Error(`Application integration patch expected one anchor, got ${count}: ${from.slice(0, 90)}`);
  return source.replace(from, to);
}

export function patchApplicationChannels(source) {
  source = once(source, '"telegram","discord","xiaoyi","mqtt"]', '"telegram","discord","slack","xiaoyi","mqtt"]');
  source = once(source, 'COLLAPSED_CHANNEL_KEYS=new Set(["telegram","discord"])', 'COLLAPSED_CHANNEL_KEYS=new Set(["telegram","discord","slack"])');
  for (const [from, to] of [
    ['discord:"channels.label_discord",', 'discord:"channels.label_discord",slack:"channels.label_slack",'],
    ['discord:"Discord",', 'discord:"Discord",slack:"Slack",'],
    ['discord:discordIcon,', 'discord:discordIcon,slack:consoleIcon,'],
    ['discord:"https://discord.com/developers/applications",', 'discord:"https://discord.com/developers/applications",slack:"https://api.slack.com/apps",'],
  ]) source = once(source, from, to);
  const fields = [
    {name:"bot_token",label:"Bot Token (xoxb-)",type:"password",required:true},
    {name:"app_token",label:"App Token (xapp-)",type:"password",required:true,helpKey:"channels.slackSetupHelp"},
    {name:"allow_all_channels",label:"channels.slackAllowAllChannels",type:"switch"},
    {name:"allowed_channel_ids",label:"channels.slackAllowedChannels",type:"textarea"},
    {name:"allowed_user_ids",label:"channels.slackAllowedUsers",type:"textarea",helpKey:"channels.slackAllowedUsersHelp"},
  ];
  source = once(source, 'const CHANNEL_FIELDS={', `const CHANNEL_FIELDS={slack:${JSON.stringify(fields)},`);
  source = once(source, 'function normalizeChannelFieldValue(fieldName,value){', 'function normalizeChannelFieldValue(fieldName,value,kind){');
  return once(source, 'if(entries.some(entry=>!/^\\d+$/.test(String(entry))))throw new Error("Invalid Discord ID");', 'const pattern=kind==="slack"?/^[A-Z][A-Z0-9]+$/:/^\\d+$/;if(entries.some(entry=>!pattern.test(String(entry))))throw new Error("Invalid channel or user ID");');
}

export function patchApplicationChannelForms(source) {
  source = once(source, 'function FormItemForField({field,disabled=!1}){', 'function FormItemForField({field,kind,disabled=!1}){');
  if (source.split('normalizeChannelFieldValue(field.name,value)').length - 1 !== 2) throw new Error('Channel form validation anchor changed');
  source = source.replaceAll('normalizeChannelFieldValue(field.name,value)', 'normalizeChannelFieldValue(field.name,value,kind)');
  source = once(source, 't("channels.discordInvalidIds")', 't(kind==="slack"?"channels.slackInvalidIds":"channels.discordInvalidIds")');
  source = once(source, 'FormItemForField,{field:f,disabled:', 'FormItemForField,{field:f,kind:selectedKind,disabled:');
  const marker = 'normalizeChannelFieldValue(k,v)';
  if (source.split(marker).length - 1 !== 2) throw new Error('Channel save anchors changed');
  source = source.replace(marker, 'normalizeChannelFieldValue(k,v,kind)');
  return source.replace(marker, 'normalizeChannelFieldValue(k,v,values.kind)');
}

export function patchApplicationConnectorCard(source) {
  source = once(source, 'disabled=entry.phase!=="available";', 'unsupportedHost=entry.available_on_host===!1,disabled=entry.phase!=="available"||unsupportedHost;');
  source = once(source, 'role:"button",tabIndex:disabled?-1:0', 'role:"button","aria-disabled":disabled,tabIndex:disabled?-1:0');
  return once(source, 'disabled?jsxRuntimeExports.jsx("div",{className:styles.typeCardFooterSpacer,"aria-hidden":!0}):', 'unsupportedHost?jsxRuntimeExports.jsx("div",{className:styles.typeCardFooter,children:t("connectors.unsupportedHost")}):disabled?jsxRuntimeExports.jsx("div",{className:styles.typeCardFooterSpacer,"aria-hidden":!0}):');
}

export function patchApplicationLocale(source) {
  const locale = source.includes('label_discord:"Discord"') && source.includes('label_feishu:"飞书"') ? 'zh' : 'en';
  const translations = JSON.parse(fs.readFileSync(fileURLToPath(new URL(`../../dashboard/src/locales/${locale}.json`, import.meta.url)), 'utf8'));
  for (const namespace of ['channels', 'connectors']) {
    const selected = Object.fromEntries(Object.entries(translations[namespace]).filter(([key]) => namespace === 'channels' ? key.startsWith('slack') || key === 'label_slack' : key === 'unsupportedHost'));
    source = once(source, `${namespace}:{`, `${namespace}:{${JSON.stringify(selected).slice(1,-1)},`);
  }
  return source;
}
