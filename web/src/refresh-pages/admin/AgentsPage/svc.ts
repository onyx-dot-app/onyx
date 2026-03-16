async function parseErrorDetail(
  res: Response,
  fallback: string
): Promise<string> {
  try {
    const body = await res.json();
    return body?.detail ?? fallback;
  } catch {
    return fallback;
  }
}

export async function deleteAgent(agentId: number): Promise<void> {
  const res = await fetch(`/api/persona/${agentId}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to delete agent"));
  }
}

export async function toggleAgentFeatured(
  agentId: number,
  currentlyFeatured: boolean
): Promise<void> {
  const res = await fetch(`/api/admin/persona/${agentId}/featured`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ featured: !currentlyFeatured }),
    credentials: "include",
  });
  if (!res.ok) {
    throw new Error(
      await parseErrorDetail(res, "Failed to toggle featured status")
    );
  }
}

export async function toggleAgentVisibility(
  agentId: number,
  currentlyVisible: boolean
): Promise<void> {
  const res = await fetch(`/api/admin/persona/${agentId}/visible`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_visible: !currentlyVisible }),
    credentials: "include",
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to toggle visibility"));
  }
}

export async function updateAgentDisplayPriorities(
  displayPriorityMap: Record<string, number>
): Promise<void> {
  const res = await fetch("/api/admin/agents/display-priorities", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_priority_map: displayPriorityMap }),
  });
  if (!res.ok) {
    throw new Error(
      await parseErrorDetail(res, "Failed to update agent order")
    );
  }
}
