// Shared chat-label helpers. A chat session created lazily (web parity) has no
// name until the backend auto-titles it after the first message, so the sidebar,
// project folder rows, and the project "Recent Chats" list all fall back to a
// "New Chat" label. Keep the constant + fallback here so the three call sites stay
// byte-identical.

export const UNNAMED_CHAT = "New Chat";

/** A chat session's display name, falling back to `UNNAMED_CHAT` when blank. */
export function chatDisplayName(name: string | null | undefined): string {
  return (name ?? "").trim() || UNNAMED_CHAT;
}
