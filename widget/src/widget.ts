/**
 * Onyx Chat Widget - Main Component
 * Orchestrates launcher/inline modes and manages widget lifecycle
 */

import { LitElement, html } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { unsafeHTML } from "lit/directives/unsafe-html.js";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { WidgetConfig, ChatMessage } from "./types/widget-types";
import { resolveConfig } from "./config/config";
import { theme } from "./styles/theme";
import { widgetStyles } from "./styles/widget-styles";
import { ApiService } from "./services/api-service";
import { processPacket } from "./services/stream-parser";
import { saveSession, loadSession, clearSession } from "./utils/storage";
import { DEFAULT_LOGO } from "./assets/logo";

@customElement("onyx-chat-widget")
export class OnyxChatWidget extends LitElement {
  static styles = [theme, widgetStyles];

  // Configuration attributes
  @property({ attribute: "backend-url" }) backendUrl?: string;
  @property({ attribute: "api-key" }) apiKey?: string;
  @property({ attribute: "agent-id", type: Number }) agentId?: number;
  @property({ attribute: "primary-color" }) primaryColor?: string;
  @property({ attribute: "background-color" }) backgroundColor?: string;
  @property({ attribute: "text-color" }) textColor?: string;
  @property({ attribute: "agent-name" }) agentName?: string;
  @property({ attribute: "logo" }) logo?: string;
  @property() mode?: "launcher" | "inline";
  @property({ attribute: "include-citations", type: Boolean })
  includeCitations?: boolean;

  // Internal state
  @state() private isOpen = false;
  @state() private chatSessionId?: string;
  @state() private messages: ChatMessage[] = [];
  @state() private isLoading = false;
  @state() private isStreaming = false;
  @state() private streamingStatus = ""; // e.g., "Searching the web...", "Generating response..."
  @state() private error?: string;
  @state() private inputValue = "";

  private config!: WidgetConfig;
  private apiService!: ApiService;
  private abortController?: AbortController;

  constructor() {
    super();
    // Configure marked options
    marked.setOptions({
      breaks: true, // Convert \n to <br>
      gfm: true, // GitHub Flavored Markdown
    });
  }

  updated(changedProperties: Map<string, any>) {
    super.updated(changedProperties);

    // Auto-scroll when messages change or streaming status changes
    if (
      changedProperties.has("messages") ||
      changedProperties.has("isStreaming")
    ) {
      this.scrollToBottom();
    }
  }

  private scrollToBottom() {
    // Use requestAnimationFrame to ensure DOM is updated
    requestAnimationFrame(() => {
      const messagesContainer = this.shadowRoot?.querySelector(".messages");
      if (messagesContainer) {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
      }
    });
  }

  connectedCallback() {
    super.connectedCallback();

    // Resolve configuration
    this.config = resolveConfig({
      backendUrl: this.backendUrl,
      apiKey: this.apiKey,
      agentId: this.agentId,
      primaryColor: this.primaryColor,
      backgroundColor: this.backgroundColor,
      textColor: this.textColor,
      agentName: this.agentName,
      logo: this.logo,
      mode: this.mode,
      includeCitations: this.includeCitations,
    });

    // Apply custom colors
    this.applyCustomColors();

    // Initialize API service
    this.apiService = new ApiService(
      this.config.backendUrl,
      this.config.apiKey,
    );

    // Load persisted session
    const stored = loadSession();
    if (stored) {
      this.chatSessionId = stored.sessionId;
      this.messages = stored.messages;
    }

    // Auto-open if inline mode
    if (this.config.mode === "inline") {
      this.isOpen = true;
    }
  }

  private applyCustomColors() {
    // Primary color (buttons, accents)
    if (this.config.primaryColor) {
      this.style.setProperty("--theme-primary-05", this.config.primaryColor);
      this.style.setProperty(
        "--theme-primary-06",
        this.adjustBrightness(this.config.primaryColor, -10),
      );
    }

    // Background color
    if (this.config.backgroundColor) {
      this.style.setProperty(
        "--background-neutral-00",
        this.config.backgroundColor,
      );
      this.style.setProperty(
        "--background-neutral-03",
        this.adjustBrightness(this.config.backgroundColor, -10),
      );
    }

    // Text color
    if (this.config.textColor) {
      this.style.setProperty("--text-04", this.config.textColor);
    }
  }

  private adjustBrightness(color: string, percent: number): string {
    const num = parseInt(color.replace("#", ""), 16);
    const amt = Math.round(2.55 * percent);
    const R = (num >> 16) + amt;
    const G = ((num >> 8) & 0x00ff) + amt;
    const B = (num & 0x0000ff) + amt;
    return (
      "#" +
      (
        0x1000000 +
        (R < 255 ? (R < 1 ? 0 : R) : 255) * 0x10000 +
        (G < 255 ? (G < 1 ? 0 : G) : 255) * 0x100 +
        (B < 255 ? (B < 1 ? 0 : B) : 255)
      )
        .toString(16)
        .slice(1)
    );
  }

  /**
   * Public API: Reset conversation
   */
  public resetConversation() {
    // Abort any active streaming request first
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = undefined;
    }

    this.messages = [];
    this.chatSessionId = undefined;
    this.error = undefined;
    this.inputValue = "";
    this.isStreaming = false;
    this.isLoading = false;
    this.streamingStatus = "";
    clearSession();
  }

  /**
   * Render markdown content safely
   */
  private renderMarkdown(content: string) {
    try {
      const htmlContent = marked.parse(content, { async: false }) as string;
      const sanitizedHTML = DOMPurify.sanitize(htmlContent);
      return unsafeHTML(sanitizedHTML);
    } catch (err) {
      console.error("Failed to parse markdown:", err);
      return content; // Fallback to plain text
    }
  }

  private toggleOpen() {
    this.isOpen = !this.isOpen;
  }

  private close() {
    if (this.config.mode === "launcher") {
      this.isOpen = false;
    }
  }

  private handleInput(e: InputEvent) {
    this.inputValue = (e.target as HTMLInputElement).value;
  }

  private handleKeyDown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      this.sendMessage();
    }
  }

  private async sendMessage() {
    const message = this.inputValue.trim();
    if (!message || this.isLoading || this.isStreaming) return;

    // Clear input immediately
    this.inputValue = "";

    // Add user message
    const userMessage: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: "user",
      content: message,
      timestamp: Date.now(),
    };
    this.messages = [...this.messages, userMessage];

    try {
      this.isStreaming = true;
      this.error = undefined;

      // Create session if needed
      if (!this.chatSessionId) {
        this.isLoading = true;
        this.chatSessionId = await this.apiService.createChatSession(
          this.config.agentId,
        );
        this.isLoading = false;
      }

      // Get parent message ID (last assistant message with a numeric ID from backend)
      const parentMessage = [...this.messages]
        .reverse()
        .find((m) => m.role === "assistant" && typeof m.id === "number");
      const parentMessageId =
        parentMessage && typeof parentMessage.id === "number"
          ? parentMessage.id
          : null;

      // Stream response
      this.abortController = new AbortController();
      let currentMessage: ChatMessage | null = null;
      let assistantMessageId: number | null = null;

      for await (const packet of this.apiService.streamMessage({
        message,
        chatSessionId: this.chatSessionId,
        parentMessageId,
        signal: this.abortController.signal,
        includeCitations: this.config.includeCitations,
      })) {
        const result = processPacket(packet, currentMessage);

        // Capture message IDs from backend and update local messages
        if (result.messageIds) {
          // Update user message ID if we got one
          if (result.messageIds.userMessageId !== null) {
            const userMsgIndex = this.messages.findIndex(
              (m) => m.id === userMessage.id,
            );
            if (userMsgIndex >= 0) {
              // Create new array to trigger reactivity
              const updatedMessage = {
                ...this.messages[userMsgIndex],
                id: result.messageIds.userMessageId,
              };
              this.messages = [
                ...this.messages.slice(0, userMsgIndex),
                updatedMessage,
                ...this.messages.slice(userMsgIndex + 1),
              ];
            }
          }
          // Store assistant message ID to apply when message is created
          assistantMessageId = result.messageIds.assistantMessageId;
        }

        // Update status if provided
        if (result.status !== undefined) {
          this.streamingStatus = result.status;
        }

        if (result.message) {
          currentMessage = result.message;

          // Apply the backend message ID if we have it and message doesn't have a numeric ID yet
          if (
            assistantMessageId !== null &&
            typeof currentMessage.id !== "number"
          ) {
            currentMessage.id = assistantMessageId;
          }

          // Update or add message
          const existingIndex = this.messages.findIndex(
            (m) => m.id === currentMessage?.id,
          );
          if (existingIndex >= 0) {
            this.messages = [
              ...this.messages.slice(0, existingIndex),
              currentMessage,
              ...this.messages.slice(existingIndex + 1),
            ];
          } else {
            this.messages = [...this.messages, currentMessage];
          }

          // Clear streaming state when message is complete
          if (!currentMessage.isStreaming) {
            this.isStreaming = false;
            this.streamingStatus = "";
          }

          // Persist session
          saveSession(this.chatSessionId, this.messages);
        }
      }
    } catch (err: any) {
      console.error("Failed to send message:", err);
      if (err.name !== "AbortError") {
        this.error = err.message || "Failed to send message";
      }
    } finally {
      this.isStreaming = false;
      this.isLoading = false;
      this.streamingStatus = "";
      this.abortController = undefined;
    }
  }

  render() {
    const showContainer = this.config.mode === "inline" || this.isOpen;
    const hasMessages = this.messages.length > 0 || this.isStreaming;
    const isCompactInline = this.config.mode === "inline" && !hasMessages;

    return html`
      ${this.config.mode === "launcher"
        ? html`
            <button
              class="launcher"
              @click=${this.toggleOpen}
              title="Open chat"
            >
              <img
                src="${this.config.logo || DEFAULT_LOGO}"
                alt="Logo"
                style="width: 32px; height: 32px; object-fit: contain;"
              />
            </button>
          `
        : ""}
      ${showContainer
        ? html`
            <div
              class="container ${this.config.mode === "inline"
                ? "inline"
                : ""} ${isCompactInline ? "compact" : ""}"
            >
              ${isCompactInline
                ? this.renderCompactInput()
                : html`
                    ${this.renderHeader()} ${this.renderMessages()}
                    ${this.renderInput()}
                  `}
            </div>
          `
        : ""}
    `;
  }

  private renderHeader() {
    return html`
      <div class="header">
        <div class="header-left">
          <div class="avatar">
            <img
              src="${this.config.logo || DEFAULT_LOGO}"
              alt="Logo"
              style="width: 100%; height: 100%; object-fit: contain;"
            />
          </div>
          <div class="header-title">
            ${this.config.agentName || "Assistant"}
          </div>
        </div>
        <div class="header-right">
          <button
            class="icon-button"
            @click=${this.resetConversation}
            title="Reset conversation"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
            >
              <path
                d="M14.448 3.10983V6.77746M14.448 6.77746H10.7803M14.448 6.77746L11.6117 4.11231C10.9547 3.45502 10.142 2.97486 9.24923 2.71664C8.35651 2.45842 7.41292 2.43055 6.50651 2.63564C5.6001 2.84072 4.76042 3.27208 4.06581 3.88945C3.3712 4.50683 2.84431 5.2901 2.53429 6.16618M1 12.8902V9.22254M1 9.22254H4.66763M1 9.22254L3.8363 11.8877C4.49326 12.545 5.30603 13.0251 6.19875 13.2834C7.09147 13.5416 8.03506 13.5694 8.94147 13.3644C9.84787 13.1593 10.6876 12.7279 11.3822 12.1105C12.0768 11.4932 12.6037 10.7099 12.9137 9.83381"
                stroke-width="1.5"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </button>
          ${this.config.mode === "launcher"
            ? html`
                <button class="icon-button" @click=${this.close} title="Close">
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 28 28"
                    fill="none"
                    stroke="currentColor"
                  >
                    <path
                      d="M21 7L7 21M7 7L21 21"
                      stroke-width="2"
                      stroke-linejoin="round"
                    />
                  </svg>
                </button>
              `
            : ""}
        </div>
      </div>
    `;
  }

  private renderMessages() {
    // Check if there's a streaming message with content
    const hasStreamingContent = this.messages.some(
      (m) => m.role === "assistant" && m.isStreaming && m.content.length > 0,
    );
    // Show ellipsis only when: streaming AND (has status text OR no content yet)
    const showEllipsis =
      this.isStreaming && (this.streamingStatus || !hasStreamingContent);

    return html`
      <div class="disclaimer">
        Responses are generated by AI and may be inaccurate
      </div>
      <div class="messages">
        ${this.error ? html` <div class="error">${this.error}</div> ` : ""}
        ${this.messages.map(
          (msg) => html`
            <div class="message ${msg.role}">
              <div class="message-bubble">
                ${msg.role === "assistant"
                  ? this.renderMarkdown(msg.content)
                  : msg.content}
              </div>
            </div>
          `,
        )}
        ${showEllipsis
          ? html`
              <div class="message assistant">
                <div class="message-bubble">
                  <div class="status-container">
                    <div class="typing-indicator">
                      <div class="typing-dot"></div>
                      <div class="typing-dot"></div>
                      <div class="typing-dot"></div>
                    </div>
                    ${this.streamingStatus
                      ? html`
                          <span class="status-text"
                            >${this.streamingStatus}</span
                          >
                        `
                      : ""}
                  </div>
                </div>
              </div>
            `
          : ""}
      </div>
    `;
  }

  private renderInput() {
    return html`
      <div class="input-wrapper">
        <div class="input-container">
          <input
            class="input"
            type="text"
            .value=${this.inputValue}
            @input=${this.handleInput}
            @keydown=${this.handleKeyDown}
            placeholder="Type your message..."
            ?disabled=${this.isLoading || this.isStreaming}
          />
          <button
            class="send-button"
            @click=${this.sendMessage}
            ?disabled=${!this.inputValue.trim() ||
            this.isLoading ||
            this.isStreaming}
            title="Send message"
          >
            <svg
              width="20"
              height="20"
              viewBox="0 0 18 18"
              fill="none"
              stroke="currentColor"
            >
              <path
                d="M8 2.6665V13.3335M8 2.6665L4 6.6665M8 2.6665L12 6.6665"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
          </button>
        </div>
        <div class="powered-by">
          Powered by
          <a
            href="https://onyx.app"
            target="_blank"
            rel="noopener noreferrer"
            style="text-decoration: underline;"
            >Onyx</a
          >
        </div>
      </div>
    `;
  }

  private renderCompactInput() {
    return html`
      <div class="compact-input-container">
        <div class="compact-avatar">
          <img
            src="${this.config.logo || DEFAULT_LOGO}"
            alt="Logo"
            style="width: 100%; height: 100%; object-fit: contain;"
          />
        </div>
        <input
          class="compact-input"
          type="text"
          .value=${this.inputValue}
          @input=${this.handleInput}
          @keydown=${this.handleKeyDown}
          placeholder="Ask ${this.config.agentName || "Assistant"} anything..."
          ?disabled=${this.isLoading || this.isStreaming}
        />
        <button
          class="send-button"
          @click=${this.sendMessage}
          ?disabled=${!this.inputValue.trim() ||
          this.isLoading ||
          this.isStreaming}
          title="Send message"
        >
          <svg
            width="18"
            height="18"
            viewBox="0 0 18 18"
            fill="none"
            stroke="currentColor"
          >
            <path
              d="M8 2.6665V13.3335M8 2.6665L4 6.6665M8 2.6665L12 6.6665"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </button>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "onyx-chat-widget": OnyxChatWidget;
  }
}
