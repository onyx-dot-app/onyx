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

export function classifyAssistants(
  user: User | null,
  assistants: MinimalPersonaSnapshot[]
) {
  if (!user) {
    return {
      visibleAssistants: assistants.filter(
        (assistant) => assistant.is_default_persona
      ),
      hiddenAssistants: [],
    };
  }

  const visibleAssistants = assistants.filter((assistant) => {
    const isVisible = user.preferences?.visible_assistants?.includes(
      assistant.id
    );
    const isNotHidden = !user.preferences?.hidden_assistants?.includes(
      assistant.id
    );

    const isBuiltIn = assistant.builtin_persona;
    const isDefault = assistant.is_default_persona;

    const isOwnedByUser = checkUserOwnsAssistant(user, assistant);

    const isShown =
      (isVisible && isNotHidden) ||
      (isNotHidden && (isBuiltIn || isDefault || isOwnedByUser));
    return isShown;
  });

  const hiddenAssistants = assistants.filter((assistant) => {
    return !visibleAssistants.includes(assistant);
  });

  return {
    visibleAssistants,
    hiddenAssistants,
  };
}

export function orderAssistantsForUser(
  assistants: MinimalPersonaSnapshot[],
  user: User | null
) {
  let orderedAssistants = [...assistants];

  if (user?.preferences?.chosen_assistants) {
    const chosenAssistantsSet = new Set(user.preferences.chosen_assistants);
    const assistantOrderMap = new Map(
      user.preferences.chosen_assistants.map((id: number, index: number) => [
        id,
        index,
      ])
    );

    // Sort chosen assistants based on user preferences
    orderedAssistants.sort((a, b) => {
      const orderA = assistantOrderMap.get(a.id);
      const orderB = assistantOrderMap.get(b.id);

      if (orderA !== undefined && orderB !== undefined) {
        return orderA - orderB;
      } else if (orderA !== undefined) {
        return -1;
      } else if (orderB !== undefined) {
        return 1;
      } else {
        return 0;
      }
    });

    // Filter out assistants not in the user's chosen list
    orderedAssistants = orderedAssistants.filter((assistant) =>
      chosenAssistantsSet.has(assistant.id)
    );
  }

  // Sort remaining assistants based on display_priority
  const remainingAssistants = assistants.filter(
    (assistant) => !orderedAssistants.includes(assistant)
  );

  remainingAssistants.sort((a, b) => {
    const priorityA = a.display_priority ?? Number.MAX_SAFE_INTEGER;
    const priorityB = b.display_priority ?? Number.MAX_SAFE_INTEGER;
    return priorityA - priorityB;
  });

  // Combine ordered chosen assistants with remaining assistants
  return [...orderedAssistants, ...remainingAssistants];
}

export function getUserCreatedAssistants(
  user: User | null,
  assistants: MinimalPersonaSnapshot[]
) {
  return assistants.filter((assistant) =>
    checkUserOwnsAssistant(user, assistant)
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
