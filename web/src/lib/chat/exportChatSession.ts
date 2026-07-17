import { BackendChatSession, BackendMessage } from "@/app/app/interfaces";
import { UNNAMED_CHAT } from "@/lib/constants";
import { downloadFile } from "@/lib/download";

export type ChatExportFormat = "text" | "markdown";

// Only user/assistant turns carry conversational content worth exporting;
// system, tool-call, and reminder messages are internal plumbing.
const EXPORTABLE_MESSAGE_TYPES = new Set(["user", "assistant"]);

function roleLabel(messageType: string): string {
  if (messageType === "user") return "User";
  if (messageType === "assistant") return "Assistant";
  return messageType;
}

function exportableMessages(session: BackendChatSession): BackendMessage[] {
  return session.messages.filter(
    (message) =>
      EXPORTABLE_MESSAGE_TYPES.has(message.message_type) &&
      message.message.trim().length > 0
  );
}

function chatSessionToText(session: BackendChatSession, title: string): string {
  const blocks = exportableMessages(session).map(
    (message) =>
      `${roleLabel(message.message_type)}:\n${message.message.trim()}`
  );
  return [title, ...blocks].join("\n\n") + "\n";
}

function chatSessionToMarkdown(
  session: BackendChatSession,
  title: string
): string {
  const blocks = exportableMessages(session).map(
    (message) =>
      `## ${roleLabel(message.message_type)}\n\n${message.message.trim()}`
  );
  return [`# ${title}`, ...blocks].join("\n\n") + "\n";
}

// Collapse anything that isn't filename-safe so the download lands cleanly
// across operating systems.
function sanitizeFilename(name: string): string {
  const trimmed = name.trim() || UNNAMED_CHAT;
  return trimmed
    .replace(/[^a-z0-9-_ ]/gi, "_")
    .replace(/\s+/g, "_")
    .slice(0, 100);
}

/**
 * Fetch a chat session's full message history and trigger a browser download
 * of its transcript as either plain text or markdown.
 */
export async function exportChatSession(
  chatSessionId: string,
  chatName: string,
  format: ChatExportFormat
): Promise<void> {
  const response = await fetch(`/api/chat/get-chat-session/${chatSessionId}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch chat session: ${response.status}`);
  }
  const session = (await response.json()) as BackendChatSession;

  const title = chatName.trim() || UNNAMED_CHAT;
  const base = sanitizeFilename(chatName);

  if (format === "markdown") {
    downloadFile(`${base}.md`, {
      content: chatSessionToMarkdown(session, title),
      mimeType: "text/markdown",
    });
  } else {
    downloadFile(`${base}.txt`, {
      content: chatSessionToText(session, title),
      mimeType: "text/plain",
    });
  }
}
