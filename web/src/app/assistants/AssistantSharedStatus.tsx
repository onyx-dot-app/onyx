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
        Public
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
          `Shared with: ${
            assistantSharedUsersWithoutOwner.length <= 4
              ? assistantSharedUsersWithoutOwner.map((u) => u.email).join(", ")
              : `${assistantSharedUsersWithoutOwner
                  .slice(0, 4)
                  .map((u) => u.email)
                  .join(", ")} and ${assistant.users.length - 4} others...`
          }`
        ) : (
          <div>
            {assistant.owner ? (
              <div>
                Shared with you by <i>{assistant.owner?.email}</i>
              </div>
            ) : (
              "Shared with you"
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
      Private
    </div>
  );
}
