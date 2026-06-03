/**
 * Widget-specific types
 */

import { ResolvedCitation } from "@/types/api-types";

/**
 * Returns the bearer credential for a single request. Called before every
 * backend call, so a host can hand back a freshly minted short-lived token.
 */
export type TokenProvider = () => string | Promise<string>;

export interface WidgetConfig {
  // Required
  backendUrl: string;

  // Static credential. Omitted when the host supplies a `tokenProvider`.
  apiKey?: string;

  // Optional - Assistant
  agentId?: number;
  agentName?: string;
  logo?: string;

  // Optional - Customization
  primaryColor?: string;
  backgroundColor?: string;
  textColor?: string;

  // Optional - Display
  mode?: "launcher" | "inline";

  // Optional - Citations
  includeCitations?: boolean;
}

export interface ChatState {
  sessionId?: string;
  messages: ChatMessage[];
  isLoading: boolean;
  error?: string;
}

export interface ChatMessage {
  id: string | number; // string for temporary local IDs, number for backend IDs
  role: "user" | "assistant";
  content: string;
  timestamp: number;
  isStreaming?: boolean;
  citations?: ResolvedCitation[];
}
