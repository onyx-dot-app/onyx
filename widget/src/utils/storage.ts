/**
 * Session storage utilities
 */

import { ChatMessage } from "@/types/widget-types";

const SESSION_KEY = "onyx-widget-session";
const SESSION_TTL = 24 * 60 * 60 * 1000; // 24 hours

export interface StoredSession {
  sessionId: string;
  messages: ChatMessage[];
  timestamp: number;
  // Who the transcript belongs to. See `deriveCredentialIdentity`.
  identity: string;
}

/**
 * Save session to sessionStorage
 */
export function saveSession(
  sessionId: string,
  messages: ChatMessage[],
  identity: string
): void {
  try {
    const session: StoredSession = {
      sessionId,
      messages,
      timestamp: Date.now(),
      identity,
    };
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } catch (e) {
    console.warn("Failed to save session:", e);
  }
}

/**
 * Load session from sessionStorage
 * Returns null if the session is missing, has expired, or belongs to someone
 * else. A stored session for another identity is discarded, so a shared tab
 * never shows the previous person's messages.
 */
export function loadSession(identity: string): StoredSession | null {
  try {
    const data = sessionStorage.getItem(SESSION_KEY);
    if (!data) return null;

    const session: StoredSession = JSON.parse(data);

    // Check if session has expired
    if (Date.now() - session.timestamp > SESSION_TTL) {
      clearSession();
      return null;
    }

    if (session.identity !== identity) {
      clearSession();
      return null;
    }

    return session;
  } catch (e) {
    console.warn("Failed to load session:", e);
    return null;
  }
}

/**
 * Clear session from sessionStorage
 */
export function clearSession(): void {
  try {
    sessionStorage.removeItem(SESSION_KEY);
  } catch (e) {
    console.warn("Failed to clear session:", e);
  }
}

/**
 * Check if a usable session exists for this identity
 */
export function hasSession(identity: string): boolean {
  return loadSession(identity) !== null;
}
