import type { MenuProps } from "antd";
import type { TFunction } from "i18next";
import { conversationsApi } from "../../../api/modules/conversations";
import { Archive } from "../../../components/arcIcons";
import { apiErrorMessage } from "../../../utils/apiError";
import { message } from "../../../utils/antdMessage";
import { emitSessionEvent } from "../hooks/chatStore";

export function archiveConversationMenuItem(
  threadId: string,
  t: TFunction,
): NonNullable<MenuProps["items"]>[number] {
  return {
    key: "archive",
    label: t("conversationLibrary.archive"),
    icon: <Archive size={14} aria-hidden />,
    onClick: async ({ domEvent }) => {
      domEvent.stopPropagation();
      try {
        const archived = await conversationsApi.archive(threadId, true);
        emitSessionEvent({
          kind: "sessionArchived",
          sessionId: threadId,
          agentId: archived.agent_id,
        });
        message.success(t("conversationLibrary.archived"));
      } catch (error) {
        message.error(
          apiErrorMessage(error, t("conversationLibrary.actionFailed"), t),
        );
      }
    },
  };
}
