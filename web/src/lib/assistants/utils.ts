import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import { User } from "../types";
import { checkUserIsNoAuthUser } from "../user";
import { personaComparator } from "@/app/admin/assistants/lib";

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

// Filter assistants based on connector status, image compatibility and visibility
export function filterAssistants(
  assistants: MinimalPersonaSnapshot[]
): MinimalPersonaSnapshot[] {
  let filteredAssistants = assistants.filter(
    (assistant) => assistant.is_visible
  );
  return filteredAssistants.sort(personaComparator);
}
