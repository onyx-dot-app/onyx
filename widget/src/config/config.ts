import { WidgetConfig } from "@/types/widget-types";

/**
 * Resolve widget configuration from attributes and environment variables
 * Priority: attributes > environment variables > defaults
 */
export function resolveConfig(attributes: Partial<WidgetConfig>): WidgetConfig {
  const config = {
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
    includeCitations: attributes.includeCitations ?? false,
  };

  if (!config.backendUrl || !config.apiKey) {
    throw new Error(
      "backendUrl and apiKey are required for the widget to function",
    );
  }

  return config;
}
