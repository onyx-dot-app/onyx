"use client";

export const toggleAssistantPinnedStatus = async (
  currentPinnedAssistantIDs: number[],
  assistantId: number,
  isPinned: boolean
) => {
  let updatedPinnedAssistantsIds = currentPinnedAssistantIDs;

  if (isPinned) {
    updatedPinnedAssistantsIds.push(assistantId);
  } else {
    updatedPinnedAssistantsIds = updatedPinnedAssistantsIds.filter(
      (id) => id !== assistantId
    );
  }

  const response = await fetch(`/api/user/pinned-assistants`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ordered_assistant_ids: updatedPinnedAssistantsIds }),
  });
  return response.ok;
};

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
