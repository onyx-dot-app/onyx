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

// crypto.randomUUID exists only in secure contexts; plain-HTTP self-hosted origins lack it.
function randomToken(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const hex = Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) =>
    b.toString(16).padStart(2, "0")
  ).join("");
  const variant = ((parseInt(hex.charAt(16), 16) & 0x3) | 0x8).toString(16);
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-${variant}${hex.slice(17, 20)}-${hex.slice(20)}`;
}

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
    const token = randomToken();
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
