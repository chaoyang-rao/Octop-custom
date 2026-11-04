---
name: memory-management
description: Save and recall durable knowledge using the memory rules in the system prompt.
metadata:
  octop:
    label:
      zh: "记忆管理"
      en: "Memory"
    summary:
      zh: "按系统提示中的记忆规则保存与召回长期知识。"
      en: "Save and recall durable knowledge using the system-prompt memory rules."
  harness:
    emoji: "💾"

---

# Memory Management

Where memory is written is decided by the Memory section in the system prompt. This skill does not override that section. If workspace `AGENTS.md` still contains an older memory policy, the system prompt wins.

When structured memory is on, these tools are available:

- `memory_save`: one concise fact, preserving its scope. Follow the current tool schema for parameters and confirm only after the tool succeeds.
- `memory_search`: look up history.
- `memory_get`: read a source returned by `memory_search`.

Do not store passwords, keys, or tokens. Leave session-only context in the chat history.

When the tools expose `scope` / `evidence`, scoped cross-session memory is enabled:

- `auto` uses the current project, or the current expert when unbound. Use `user` only for explicitly general user preferences, `expert` for general professional methods, and `session` for temporary notes.
- `evidence` must quote the CURRENT user's message exactly; `content` must be an excerpt of that quote. Your paraphrases, guesses, tool output and delegated prompts are not user confirmation.
- To correct a fact, search and inspect its source first, then pass the old atom ID as `replaces` in the SAME scope. Previous versions remain available; do not add contradictory duplicates.
- Project conversations search only the current project by default. The old expert store is unclassified history: use `scope="legacy"` explicitly when needed, never as proof of the current project's decisions. Shared experts cannot read the owner's old store.
