import {
  ConsumerModelCatalog,
  ConsumerModelPreference,
} from "@/lib/consumerModels/types";

export async function updateConsumerModelPreference(
  profileId: string
): Promise<ConsumerModelPreference> {
  const response = await fetch("/api/user/model-preference", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ profile_id: profileId }),
  });

  if (!response.ok) {
    throw new Error("Failed to update model preference");
  }

  return response.json();
}

export type { ConsumerModelCatalog, ConsumerModelPreference };
