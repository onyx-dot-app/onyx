export async function forgotPassword(email: string): Promise<void> {
  const response = await fetch(`/api/auth/forgot-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });

  if (!response.ok) {
    const error = await response.json();
    const errorMessage =
      error?.detail || "An error occurred during password reset.";
    throw new Error(errorMessage);
  }
}

export async function resetPassword(
  token: string,
  password: string
): Promise<void> {
  const response = await fetch(`/api/auth/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, password }),
  });

  if (!response.ok) {
    const error = await response.json();
    if (error?.detail?.code === "RESET_PASSWORD_INVALID_PASSWORD") {
      throw new Error(error.detail.reason || "Invalid password");
    }
    const errorMessage =
      error?.detail || "An error occurred during password reset.";
    throw new Error(errorMessage);
  }
}

export async function requestEmailVerification(
  email: string
): Promise<Response> {
  return fetch("/api/auth/request-verify-token", {
    headers: { "Content-Type": "application/json" },
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export async function verifyEmail(token: string): Promise<void> {
  const response = await fetch("/api/auth/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });

  if (!response.ok) {
    let detail = "unknown error";
    try {
      detail = (await response.json()).detail;
    } catch {
      // ignore parse failure
    }
    throw new Error(detail);
  }
}

export async function impersonateUser(
  email: string,
  apiKey: string
): Promise<void> {
  const response = await fetch("/api/tenants/impersonate", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({ email }),
    credentials: "same-origin",
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error?.detail || "Failed to impersonate user");
  }
}
