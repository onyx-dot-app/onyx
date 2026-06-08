// A lazily-created chat session (web parity) has no name until the backend
// auto-titles it; shared here so the sidebar, folder rows, and recent-chats list
// fall back to the same label.

export const UNNAMED_CHAT = "New Chat";

export function chatDisplayName(name: string | null | undefined): string {
  return (name ?? "").trim() || UNNAMED_CHAT;
}
