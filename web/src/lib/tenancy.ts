export const setTenantId = async (tenantId: string) => {
  const response = await fetch("/api/auth/jwt", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ tenantId }),
  });

  if (response.ok) {
    const { token } = await response.json();
    document.cookie = `fastapiusersauth=${token}; path=/; secure; samesite=strict`;
  } else {
    console.error("Failed to set tenant ID in JWT");
  }
};
