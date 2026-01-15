import { WidgetConfig } from "@/types/widget-types";

/**
 * Default support assistant prompt (used when agentId not provided)
 */
export const DEFAULT_SUPPORT_PROMPT = `You are a helpful customer support assistant. Your role is to:
- Answer customer questions clearly and concisely
- Be friendly and professional
- Direct users to relevant documentation or resources when available
- Escalate complex issues if needed

Always prioritize the customer's needs and provide accurate information.`;

/**
 * Resolve widget configuration from attributes and environment variables
 * Priority: attributes > environment variables > defaults
 */
export function resolveConfig(attributes: Partial<WidgetConfig>): WidgetConfig {
  return {
    backendUrl:
      attributes.backendUrl || import.meta.env.VITE_WIDGET_BACKEND_URL || "",
    apiKey: attributes.apiKey || import.meta.env.VITE_WIDGET_API_KEY || "",
    agentId: attributes.agentId,
    primaryColor: attributes.primaryColor,
    backgroundColor: attributes.backgroundColor,
    textColor: attributes.textColor,
    agentName: attributes.agentName || "Assistant",
    logo: attributes.logo,
    mode: attributes.mode || "launcher",
  };
}
