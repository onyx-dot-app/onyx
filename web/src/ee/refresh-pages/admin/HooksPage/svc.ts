import {
  HookCreateRequest,
  HookExecutionRecord,
  HookResponse,
  HookUpdateRequest,
  HookValidateResponse,
} from "@/ee/refresh-pages/admin/HooksPage/interfaces";

export class HookAuthError extends Error {}
export class HookTimeoutError extends Error {}
export class HookConnectError extends Error {}

async function parseError(res: Response, fallback: string): Promise<Error> {
  try {
    const body = await res.json();
    if (body?.error_code === "CREDENTIAL_INVALID") {
      return new HookAuthError(body?.detail ?? "Invalid API key.");
    }
    if (body?.error_code === "GATEWAY_TIMEOUT") {
      return new HookTimeoutError(body?.detail ?? "Connection timed out.");
    }
    if (body?.error_code === "BAD_GATEWAY") {
      return new HookConnectError(
        body?.detail ?? "Could not connect to endpoint."
      );
    }
    return new Error(body?.detail ?? fallback);
  } catch (err) {
    console.error("parseError: failed to parse error response body:", err);
    return new Error(fallback);
  }
}

export async function createHook(
  req: HookCreateRequest
): Promise<HookResponse> {
  const res = await fetch("/api/admin/hooks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    throw await parseError(res, "Failed to create hook");
  }
  return res.json();
}

export async function updateHook(
  id: number,
  req: HookUpdateRequest
): Promise<HookResponse> {
  const res = await fetch(`/api/admin/hooks/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    throw await parseError(res, "Failed to update hook");
  }
  return res.json();
}

export async function deleteHook(id: number): Promise<void> {
  const res = await fetch(`/api/admin/hooks/${id}`, { method: "DELETE" });
  if (!res.ok) {
    throw await parseError(res, "Failed to delete hook");
  }
}

export async function activateHook(id: number): Promise<HookResponse> {
  const res = await fetch(`/api/admin/hooks/${id}/activate`, {
    method: "POST",
  });
  if (!res.ok) {
    throw await parseError(res, "Failed to activate hook");
  }
  return res.json();
}

export async function deactivateHook(id: number): Promise<HookResponse> {
  const res = await fetch(`/api/admin/hooks/${id}/deactivate`, {
    method: "POST",
  });
  if (!res.ok) {
    throw await parseError(res, "Failed to deactivate hook");
  }
  return res.json();
}

export async function validateHook(id: number): Promise<HookValidateResponse> {
  const res = await fetch(`/api/admin/hooks/${id}/validate`, {
    method: "POST",
  });
  if (!res.ok) {
    throw await parseError(res, "Failed to validate hook");
  }
  return res.json();
}

export async function fetchExecutionLogs(
  id: number,
  limit = 20
): Promise<HookExecutionRecord[]> {
  const res = await fetch(
    `/api/admin/hooks/${id}/execution-logs?limit=${limit}`
  );
  if (!res.ok) {
    throw await parseError(res, "Failed to fetch execution logs");
  }
  return res.json();
}
