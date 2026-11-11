export async function generateScimToken(name: string) {
  return fetch("/api/admin/enterprise-settings/scim/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}
