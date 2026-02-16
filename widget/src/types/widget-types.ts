/**
 * Widget-specific types
 */

export interface WidgetConfig {
  // Required
  backendUrl: string;
  apiKey: string;

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
}
