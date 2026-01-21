/**
 * Onyx Chat Widget - Entry Point
 * Exports the main web component
 */

import { OnyxChatWidget } from "./widget";

// Define the custom element
if (
  typeof customElements !== "undefined" &&
  !customElements.get("onyx-chat-widget")
) {
  customElements.define("onyx-chat-widget", OnyxChatWidget);
}

// Export for use in other modules
export { OnyxChatWidget };
export * from "./types/api-types";
export * from "./types/widget-types";
