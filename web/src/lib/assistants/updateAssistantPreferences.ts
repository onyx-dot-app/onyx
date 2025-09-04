"use client";

export async function updateUserAssistantList(
  chosenAssistants: number[]
): Promise<boolean> {
  const response = await fetch("/api/user/assistant-list", {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ chosen_assistants: chosenAssistants }),
  });

  return response.ok;
}
export async function updateAssistantVisibility(
  assistantId: number,
  show: boolean
): Promise<boolean> {
  const response = await fetch(
    `/api/user/assistant-list/update/${assistantId}?show=${show}`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
    }
  );

  return response.ok;
}

export async function removeAssistantFromList(
  assistantId: number
): Promise<boolean> {
  return updateAssistantVisibility(assistantId, false);
}

export async function addAssistantToList(
  assistantId: number
): Promise<boolean> {
  return updateAssistantVisibility(assistantId, true);
}

export async function addAssistantToListAndPin(
  assistantId: number,
  currentPinnedAssistantIds: number[] = []
): Promise<boolean> {
  // First add to chosen assistants list
  const visibilitySuccess = await updateAssistantVisibility(assistantId, true);
  if (!visibilitySuccess) {
    return false;
  }

  // Then pin the assistant by appending to existing pinned list
  try {
    const updatedPinnedAssistantsIds = [
      ...currentPinnedAssistantIds,
      assistantId,
    ];
    const response = await fetch(`/api/user/pinned-assistants`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ordered_assistant_ids: updatedPinnedAssistantsIds,
      }),
    });
    return response.ok;
  } catch (error) {
    console.error("Error pinning assistant:", error);
    return false;
  }
}

export async function moveAssistantUp(
  assistantId: number,
  chosenAssistants: number[]
): Promise<boolean> {
  const index = chosenAssistants.indexOf(assistantId);
  if (index > 0) {
    const chosenAssistantPrev = chosenAssistants[index - 1];
    const chosenAssistant = chosenAssistants[index];
    if (chosenAssistantPrev === undefined || chosenAssistant === undefined) {
      return false;
    }

    chosenAssistants[index - 1] = chosenAssistant;
    chosenAssistants[index] = chosenAssistantPrev;
    return updateUserAssistantList(chosenAssistants);
  }
  return false;
}

export async function moveAssistantDown(
  assistantId: number,
  chosenAssistants: number[]
): Promise<boolean> {
  const index = chosenAssistants.indexOf(assistantId);
  if (index < chosenAssistants.length - 1) {
    const chosenAssistantNext = chosenAssistants[index + 1];
    const chosenAssistant = chosenAssistants[index];
    if (chosenAssistantNext === undefined || chosenAssistant === undefined) {
      return false;
    }

    chosenAssistants[index + 1] = chosenAssistant;
    chosenAssistants[index] = chosenAssistantNext;

    return updateUserAssistantList(chosenAssistants);
  }
  return false;
}

export const reorderPinnedAssistants = async (
  assistantIds: number[]
): Promise<boolean> => {
  const response = await fetch(`/api/user/pinned-assistants`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ordered_assistant_ids: assistantIds }),
  });
  return response.ok;
};
