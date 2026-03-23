export async function extractErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body?.detail || body?.error_code || "";
  } catch {
    return "";
  }
}

export async function requestEmailVerification(email: string) {
  return await fetch("/api/auth/request-verify-token", {
    headers: {
      "Content-Type": "application/json",
    },
    method: "POST",
    body: JSON.stringify({
      email: email,
    }),
  });
}
