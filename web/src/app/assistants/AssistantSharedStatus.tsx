import i18n from "@/i18n/init-server";
import k from "./../../i18n/keys";
import { User } from "@/lib/types";
import { Persona } from "../admin/assistants/interfaces";
import { checkUserOwnsAssistant } from "@/lib/assistants/checkOwnership";
import { FiLock, FiUnlock } from "react-icons/fi";

export function AssistantSharedStatusDisplay({
  assistant,
  user,
  size = "sm",
}: {
  assistant: Persona;
  user: User | null;
  size?: "sm" | "md" | "lg";
}) {
  const isOwnedByUser = checkUserOwnsAssistant(user, assistant);

  const assistantSharedUsersWithoutOwner = (assistant.users || [])?.filter(
    (u) => u.id !== assistant.owner?.id
  );

  if (assistant.is_public) {
    return (
      <div
        className={`text-subtle ${
          size === "sm" ? "text-sm" : size === "md" ? "text-base" : "text-lg"
        } flex items-center`}
      >
        <FiUnlock className="mr-1" />
        {i18n.t(k.PUBLIC)}
      </div>
    );
  }

  if (assistantSharedUsersWithoutOwner.length > 0) {
    return (
      <div
        className={`text-subtle ${
          size === "sm" ? "text-sm" : size === "md" ? "text-base" : "text-lg"
        } flex items-center`}
      >
        <FiUnlock className="mr-1" />
        {isOwnedByUser ? (
          `${i18n.t(k.SHARED_WITH)} ${
            assistantSharedUsersWithoutOwner.length <= 4
              ? assistantSharedUsersWithoutOwner
                  .map((u) => u.email)
                  .join(i18n.t(k._3))
              : `${assistantSharedUsersWithoutOwner
                  .slice(0, 4)
                  .map((u) => u.email)
                  .join(i18n.t(k._3))} ${i18n.t(k.AND)} ${
                  assistant.users.length - 4
                } ${i18n.t(k.OTHERS)}`
          }`
        ) : (
          <div>
            {assistant.owner ? (
              <div>
                {i18n.t(k.SHARED_WITH_YOU_BY)} <i>{assistant.owner?.email}</i>
              </div>
            ) : (
              i18n.t(k.SHARED_WITH_YOU)
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      className={`text-subtle ${
        size === "sm" ? "text-sm" : size === "md" ? "text-base" : "text-lg"
      } flex items-center`}
    >
      <FiLock className="mr-1" />
      {i18n.t(k.PRIVATE1)}
    </div>
  );
}
