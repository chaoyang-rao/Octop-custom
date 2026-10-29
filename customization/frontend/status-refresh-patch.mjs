/** Keep a single app-wide status refresher and a consistent pending state. */
import { EXPERT_WORK_MESSAGES } from '../packages/octop/dashboard/assets/expert-work-status.js';
const oldPolling = 'reactExports.useEffect(()=>{const refreshBadges=()=>void refreshAgents({silent:!0});refreshBadges();const intervalId=window.setInterval(refreshBadges,1e4),onVisibility=()=>{document.visibilityState==="visible"&&refreshBadges()};return document.addEventListener("visibilitychange",onVisibility),()=>{window.clearInterval(intervalId),document.removeEventListener("visibilitychange",onVisibility)}},[refreshAgents]),';
const oldStatus = 'function resolveSessionWorkStatus(session,liveWorkingIds){return liveWorkingIds.has(session.id)||session.turnActive?"working":session.awaitingUser?"waiting":"idle"}';
const newStatus = 'function resolveSessionWorkStatus(session,liveWorkingIds){return session.awaitingUser?"waiting":liveWorkingIds.has(session.id)||session.turnActive?"working":"idle"}';

function replaceOnce(source, before, after) {
  if (source.split(before).length - 1 !== 1) throw new Error('Expert status integration anchor changed');
  return source.replace(before, after);
}

export const patchChatStatusPollingSource = source => replaceOnce(source, oldPolling, '');
export const patchSessionStatusPriority = source => replaceOnce(source, oldStatus, newStatus);

export function patchExpertStatusLocaleSource(source) {
  const entries = [['zh', '"sessionWorking":"进行中",'], ['en', '"sessionWorking":"In progress",']];
  const found = entries.filter(([, anchor]) => source.includes(anchor));
  if (found.length !== 1 || source.includes('"expertWorkStatus":')) throw new Error('Expert work locale anchor changed');
  const [language, anchor] = found[0];
  const labels = Object.fromEntries(Object.entries(EXPERT_WORK_MESSAGES[language]).map(([kind, words]) => [kind, words[0]]));
  const details = Object.fromEntries(Object.entries(EXPERT_WORK_MESSAGES[language]).map(([kind, words]) => [kind, words[1]]));
  const enabled = language === 'zh' ? '已启用' : 'Enabled';
  const payload = JSON.stringify({ expertWorkStatus: labels, expertWorkDetail: details, expertWorkEnabled: enabled }).slice(1, -1)
    .replace(/['`$]/g, char => `\\u${char.charCodeAt(0).toString(16).padStart(4, '0')}`);
  return replaceOnce(source, anchor, `${anchor}${payload},`);
}
