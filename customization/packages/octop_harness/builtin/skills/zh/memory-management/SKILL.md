---
name: memory-management
description: 按系统提示中的记忆规则保存和召回长期知识。
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

# 记忆管理

记忆写到哪里，以系统提示中的「记忆」规则为准。本技能不覆盖该规则。工作区 `AGENTS.md` 里如果还有旧的记忆写法，同样以系统提示为准。

结构化记忆开启时可以使用：

- `memory_save`：一条简洁事实，保留作用范围；具体参数以当前工具定义为准。工具成功后才能确认已记住。
- `memory_search`：查找历史。
- `memory_get`：查看 `memory_search` 返回的来源。

密码、密钥、Token 不进入记忆。仅限当前对话的内容留在聊天记录里。

当工具提供 `scope` / `evidence` 参数时，已经启用按范围管理的跨会话记忆：

- `auto` 默认当前项目，未绑定项目时使用当前专家；`user` 仅用于用户明确表达的通用偏好，`expert` 用于通用专业经验，`session` 用于临时记录。
- `evidence` 必须是本轮用户消息里的原文，`content` 必须取自这段引文，不能把自己的改写、猜测、工具输出或其他专家的派工提示当成用户确认。
- 纠正旧结论时，先检索并查看来源，再传入同范围的旧 atom ID 作为 `replaces`；旧版本保留，不重复保存互相矛盾的事实。
- 项目会话默认只查当前项目。旧专家库为未分类历史；仅在明确需要时使用 `scope="legacy"`，不能当作当前项目的既定结论。共享专家不能访问所有者的旧库。
