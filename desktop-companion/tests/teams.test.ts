import test from "node:test";
import assert from "node:assert/strict";
import {
  initialBinding,
  consumeFrame,
  sessionKey,
  type Agent,
  type Message,
} from "../web/core.ts";
import {
  markTeams,
  teamProblem,
  liveTeamSpeakers,
  type TeamRecord,
} from "../web/teams.ts";
import { canFlushQueue } from "../web/controls.ts";
const team: TeamRecord = {
  team_id: "team",
  agent_id: "team",
  name: "业务组",
  kind: "team",
  primary_agent_id: "host",
  primary_agent_name: "小通",
  member_ids: ["host", "a", "b"],
  members: [
    { agent_id: "host", name: "小通" },
    { agent_id: "a", name: "售后" },
    { agent_id: "b", name: "词元" },
  ],
};
const agents: Agent[] = [
  { id: "host", name: "小通" },
  { id: "a", name: "售后" },
  { id: "b", name: "词元" },
  { id: "team", name: "售后团队" },
];
test("teams never replace the expert defaults or silently become a solo chat", () => {
  const marked = markTeams(agents, [team]);
  assert.equal(marked.at(-1)?.is_team, true);
  assert.equal(initialBinding("team", marked, []).agentId, "");
  assert.equal(initialBinding("aftersales", marked, []).agentId, "a");
  assert.notEqual(
    sessionKey("team", 1, "team", "ctx"),
    sessionKey("host", 1, "aftersales", "ctx"),
  );
});
test("team admission pins the real Xiaotong primary and all currently allowed members", () => {
  const allowed = markTeams(agents, [team]);
  assert.equal(teamProblem(team, allowed), undefined);
  assert.ok(
    teamProblem({ ...team, primary_agent_name: "其他主持人" }, allowed),
  );
  assert.ok(teamProblem({ ...team, member_ids: ["a", "b"] }, allowed));
  assert.ok(
    teamProblem(
      team,
      allowed.filter((a) => a.id !== "b"),
    ),
  );
  assert.ok(teamProblem({ ...team, member_ids: ["host"] }, allowed));
});
test("interleaved experts and their done frames stay in separate message bubbles", () => {
  let messages: Message[] = [];
  const names = (id: string) => (id === "host" ? "小通" : "同名专家");
  for (const frame of [
    { type: "token", agent_id: "a", content: "A1" },
    { type: "token", agent_id: "b", content: "B1" },
    { type: "token", agent_id: "a", content: "A2" },
    { type: "done", agent_id: "a" },
    { type: "token", agent_id: "b", content: "B2" },
  ])
    messages = consumeFrame(messages, frame, names, "team");
  assert.equal(messages.length, 2);
  assert.equal(messages[0].text, "A1A2");
  assert.equal(messages[1].text, "B1B2");
  assert.equal(messages[0].pending, false);
  assert.equal(messages[1].pending, true);
  messages = consumeFrame(
    messages,
    {
      type: "token",
      speaker_agent_id: "host",
      agent_id: "team",
      team_wrapup: true,
      content: "汇总",
    },
    names,
    "team",
  );
  assert.equal(messages.at(-1)?.speaker, "小通");
  assert.equal(messages.at(-1)?.text, "汇总");
});
test("member work keeps the next message queued after the host turn ends", () => {
  let speakers = liveTeamSpeakers([], { type: "token", agent_id: "a" }, team);
  speakers = liveTeamSpeakers(speakers, { type: "token", agent_id: "b" }, team);
  speakers = liveTeamSpeakers(speakers, { type: "done", agent_id: "a" }, team);
  assert.deepEqual(speakers, ["b"]);
  const room = {
    busy: false,
    approvals: [],
    queue: [{ id: "q", text: "next", files: [] }],
    teamSpeakers: speakers,
  };
  assert.equal(canFlushQueue(room), false);
  speakers = liveTeamSpeakers(speakers, { type: "done", agent_id: "b" }, team);
  assert.equal(canFlushQueue({ ...room, teamSpeakers: speakers }), true);
});
