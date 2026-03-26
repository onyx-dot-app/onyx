import {
  HookCreateRequest,
  HookResponse,
  HookUpdateRequest,
  HookValidateResponse,
} from "@/refresh-pages/admin/HooksPage/interfaces";

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

export async function createHook(
  req: HookCreateRequest
): Promise<HookResponse> {
  const res = await fetch("/api/admin/hooks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to create hook"));
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
    throw new Error(await parseErrorDetail(res, "Failed to update hook"));
  }
  return res.json();
}

export async function deleteHook(id: number): Promise<void> {
  const res = await fetch(`/api/admin/hooks/${id}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to delete hook"));
  }
}

export async function activateHook(id: number): Promise<HookResponse> {
  const res = await fetch(`/api/admin/hooks/${id}/activate`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to activate hook"));
  }
  return res.json();
}

export async function deactivateHook(id: number): Promise<HookResponse> {
  const res = await fetch(`/api/admin/hooks/${id}/deactivate`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to deactivate hook"));
  }
  return res.json();
}

export async function validateHook(id: number): Promise<HookValidateResponse> {
  const res = await fetch(`/api/admin/hooks/${id}/validate`, {
    method: "POST",
  });
  if (!res.ok) {
    throw new Error(await parseErrorDetail(res, "Failed to validate hook"));
  }
  return res.json();
}
