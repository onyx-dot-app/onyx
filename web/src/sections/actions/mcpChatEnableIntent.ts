import * as yup from "yup";

const storageKey = "onyx:mcp-chat-enable";
const lifetimeMs = 5 * 60 * 1000;
const intentSchema = yup
  .object({
    token: yup.string().uuid().required(),
    userId: yup.string().required(),
    serverId: yup.number().integer().positive().required(),
    origin: yup.string().required(),
    expiresAt: yup.number().required(),
  })
  .noUnknown();

interface EnableScope {
  userId: string | undefined;
  serverId: number;
}

export function mintMcpChatEnableIntent({
  userId,
  serverId,
}: EnableScope): string | null {
  if (!userId || !Number.isSafeInteger(serverId) || serverId <= 0) return null;
  try {
    const token = crypto.randomUUID();
    window.sessionStorage.setItem(
      storageKey,
      JSON.stringify({
        token,
        userId,
        serverId,
        origin: window.location.origin,
        expiresAt: Date.now() + lifetimeMs,
      })
    );
    return token;
  } catch {
    return null;
  }
}

export function consumeMcpChatEnableIntent(
  token: string | null | undefined,
  { userId, serverId }: EnableScope
): boolean {
  if (!token) return false;
  try {
    const storage = window.sessionStorage;
    const raw = storage.getItem(storageKey);
    if (!raw) return false;
    const intent = intentSchema.validateSync(JSON.parse(raw), { strict: true });
    if (intent.token !== token) return false;
    storage.removeItem(storageKey);
    return (
      intent.userId === userId &&
      intent.serverId === serverId &&
      intent.origin === window.location.origin &&
      intent.expiresAt > Date.now() &&
      intent.expiresAt <= Date.now() + lifetimeMs
    );
  } catch {
    return false;
  }
}

export function clearMcpChatEnableIntent(
  token: string | null | undefined
): void {
  if (!token) return;
  try {
    const storage = window.sessionStorage;
    const raw = storage.getItem(storageKey);
    if (
      raw &&
      intentSchema.validateSync(JSON.parse(raw), { strict: true }).token ===
        token
    )
      storage.removeItem(storageKey);
  } catch {}
}
