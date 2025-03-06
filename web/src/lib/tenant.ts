export async function completeTenantSetup(email: string): Promise<void> {
  const response = await fetch(`/api/tenants/complete-setup`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ email }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Failed to complete tenant setup: ${errorText}`);
  }
}
