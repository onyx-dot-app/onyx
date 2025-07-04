import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { User } from "../types";
import { checkUserIsNoAuthUser } from "../user";

export function checkUserOwnsAssistant(
  user: User | null,
  assistant: MinimalPersonaSnapshot
) {
  return checkUserIdOwnsAssistant(user?.id, assistant);
}

export function checkUserIdOwnsAssistant(
  userId: string | undefined,
  assistant: MinimalPersonaSnapshot
) {
  return (
    (!userId ||
      checkUserIsNoAuthUser(userId) ||
      assistant.owner?.id === userId) &&
    !assistant.builtin_persona
  );
}
