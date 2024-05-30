import { Persona } from "@/app/admin/assistants/interfaces";
import { User } from "../types";
import { checkUserIsNoAuthUser } from "../user";

export function checkUserOwnsAssistant(user: User | null, assistant: Persona) {
  return checkUserIdOwnsAssistant(user?.id, assistant);
}

export function checkUserIdOwnsAssistant(
  userId: string | undefined,
  assistant: Persona
) {
  return (
    (!userId ||
      checkUserIsNoAuthUser(userId) ||
      assistant.owner?.id === userId) &&
    !assistant.default_persona
  );
}
