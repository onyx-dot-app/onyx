import { Persona } from "@/app/admin/assistants/interfaces";
import { User } from "../types";

export function orderAssistantsForUser(
  assistants: Persona[],
  user: User | null
) {
  if (user && user.preferences && user.preferences.chosen_assistants) {
    const chosenAssistantsSet = new Set(user.preferences.chosen_assistants);
    const assistantOrderMap = new Map(
      user.preferences.chosen_assistants.map((id: number, index: number) => [
        id,
        index,
      ])
    );

    assistants = assistants.filter((assistant) =>
      chosenAssistantsSet.has(assistant.id)
    );

    assistants.sort((a, b) => {
      const orderA = assistantOrderMap.get(a.id) ?? Number.MAX_SAFE_INTEGER;
      const orderB = assistantOrderMap.get(b.id) ?? Number.MAX_SAFE_INTEGER;
      return orderA - orderB;
    });
  }
  return assistants;
}
