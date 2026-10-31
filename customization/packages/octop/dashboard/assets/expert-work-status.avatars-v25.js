/** Render account-visible activity without treating an enabled expert as busy. */
export function deriveExpertWorkStatus(agent) {
  if (agent.bridge_disconnected) return [{ kind: 'disconnected', count: null }];
  const status = agent.work_status;
  const lifecycle = agent.state === 'failed' || agent.state === 'error'
    ? 'failed'
    : agent.state === 'created' || agent.state === 'stopped'
      ? 'stopped'
      : agent.state === 'starting' || agent.state === 'stopping'
        ? agent.state
        : status === 'stopped' || status === 'starting' || status === 'stopping' || status === 'failed'
          ? status
          : null;
  if (lifecycle) return [{ kind: lifecycle, count: null }];
  if (status === 'unknown') return [{ kind: 'unknown', count: null }];
  if (status !== 'working' && status !== 'waiting' && status !== 'idle') {
    return [{ kind: agent.bridge ? 'remote_online' : agent.state === 'running' ? 'online' : 'unknown', count: null }];
  }
  const count = value => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
  const working = count(agent.working_count), waiting = count(agent.waiting_count), badges = [];
  if (status === 'working' || (working ?? 0) > 0) badges.push({ kind: 'working', count: working && working > 0 ? working : null });
  if (status === 'waiting' || (waiting ?? 0) > 0) badges.push({ kind: 'waiting', count: waiting && waiting > 0 ? waiting : null });
  return badges.length ? badges : [{ kind: 'idle', count: null }];
}

export const EXPERT_WORK_MESSAGES = {
  zh: {
    working: ['工作中', '正在运行的会话'], waiting: ['待确认', '等待确认或回复的会话'],
    idle: ['空闲', '当前账号没有正在运行或等待确认的会话'],
    stopped: ['未启动', '专家尚未启用'], failed: ['异常', '专家未正常运行，请查看专家设置'],
    starting: ['启动中', '专家正在启动'], stopping: ['停止中', '专家正在停止'],
    online: ['在线', '专家已启用，后端尚未提供工作状态'],
    remote_online: ['远端在线', '云端连接正常，远端尚未提供工作状态'],
    disconnected: ['连接断开', '云端连接已断开，无法确认远端工作状态'],
    unknown: ['状态待同步', '工作状态尚未同步，请稍候'],
  },
  en: {
    working: ['Working', 'Running conversations'], waiting: ['Waiting', 'Conversations waiting for approval or a reply'],
    idle: ['Idle', 'No running or waiting conversations are visible to this account'],
    stopped: ['Not started', 'The expert is not enabled'], failed: ['Error', 'The expert is not running normally; check its settings'],
    starting: ['Starting', 'The expert is starting'], stopping: ['Stopping', 'The expert is stopping'],
    online: ['Online', 'The expert is enabled; the backend has not supplied work status'],
    remote_online: ['Remote online', 'The remote link is connected; work status has not been supplied'],
    disconnected: ['Disconnected', 'The remote link is disconnected; remote work status is unavailable'],
    unknown: ['Sync pending', 'Work status is not synchronized yet'],
  },
};

export function createExpertWorkStatus({ React, useTranslation }) {
  const h = React.createElement;
  return function ExpertWorkStatus({ agent }) {
    const { t, i18n } = useTranslation();
    const messages = EXPERT_WORK_MESSAGES[String(i18n?.language || 'en').toLowerCase().startsWith('zh') ? 'zh' : 'en'];
    return h('span', { className: 'octop-expert-work-status', 'data-testid': 'expert-work-status' },
      ...deriveExpertWorkStatus(agent).map(({ kind, count }) => {
        const [fallback, detail] = messages[kind];
        const label = t(`chat.expertWorkStatus.${kind}`, { defaultValue: fallback });
        const text = count === null ? label : `${label} ${count}`;
        const translatedDetail = t(`chat.expertWorkDetail.${kind}`, { defaultValue: detail });
        const title = count === null ? translatedDetail : `${translatedDetail}: ${count}`;
        return h('span', { key: kind, className: 'octop-expert-work-badge', 'data-work-status': kind, title,
          'aria-label': `${agent.name || ''}: ${text}` }, h('span', { className: 'octop-expert-work-indicator', 'aria-hidden': true }), text);
      }));
  };
}
