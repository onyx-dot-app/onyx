/**
 * Onyx Chat Widget - Main Component
 * Orchestrates launcher/inline modes and manages widget lifecycle
 */

import { LitElement, html, TemplateResult } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import { unsafeHTML } from "lit/directives/unsafe-html.js";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { WidgetConfig, ChatMessage, TokenProvider } from "./types/widget-types";
import {
  Packet,
  SearchDocument,
  ResolvedCitation,
  ToolApprovalRequest,
} from "./types/api-types";
import {
  resolveConfig,
  resolveAuthToken,
  deriveCredentialIdentity,
} from "./config/config";
import { theme } from "./styles/theme";
import { widgetStyles } from "./styles/widget-styles";
import { ApiError, ApiService } from "./services/api-service";
import {
  APPROVAL_PENDING_ERROR_CODE,
  ApprovalDecision,
  ApprovalEntry,
  ApprovalStatus,
  approvalDeadline,
  approvalRecord,
  approvalStatus,
  argumentRows,
  decidedStatus,
  findPendingApproval,
  readOutcome,
} from "./services/approvals";
import { MessageIDs, processPacket } from "./services/stream-parser";
import { saveSession, loadSession, clearSession } from "./utils/storage";
import { DEFAULT_LOGO } from "./assets/logo";

const ICON_LOADER = html`<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M8 1.5v2M8 12.5v2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M1.5 8h2M12.5 8h2M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4"/></svg>`;
const ICON_CHECK = html`<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="12" height="12" rx="2"/><path d="M5.5 8l2 2 3-4"/></svg>`;
const ICON_X = html`<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M12 4L4 12M4 4l8 8"/></svg>`;
const ICON_CLOCK = html`<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="6.5"/><path d="M8 4.5V8l2.5 1.5"/></svg>`;

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
  // Reflected so `:host([mode="inline"])` also matches when set as a property.
  @property({ reflect: true }) mode?: "launcher" | "inline";
  @property({ attribute: "include-citations", type: Boolean })
  includeCitations?: boolean;
  @property({ attribute: "start-expanded", type: Boolean })
  startExpanded?: boolean;

  // Assigned as a JS property, since a function cannot ride an HTML attribute.
  // Takes precedence over `api-key` and keeps the credential out of the markup.
  @property({ attribute: false }) tokenProvider?: TokenProvider;

  // Internal state
  @state() private isOpen = false;
  @state() private chatSessionId?: string;
  @state() private messages: ChatMessage[] = [];
  @state() private isLoading = false;
  @state() private isStreaming = false;
  @state() private streamingStatus = ""; // e.g., "Searching the web...", "Generating response..."
  @state() private error?: string;
  @state() private inputValue = "";
  // Approval ids whose decision request is in flight or failed
  @state() private submittingApprovals = new Set<string>();
  @state() private failedApprovals = new Set<string>();
  // Decisions from this widget, by approval id, until the stream resolves them
  @state() private localApprovalStatuses = new Map<string, ApprovalStatus>();

  private config!: WidgetConfig;
  private apiService!: ApiService;
  private sessionRestored = false;
  private abortController?: AbortController;
  // Citation state — plain fields (not @state) since Map mutations don't trigger Lit re-renders
  private documentMap = new Map<string, SearchDocument>();
  private citationMap = new Map<number, string>();

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

    // A host that assigns `tokenProvider` after mount only becomes able to
    // identify the stored transcript now.
    if (changedProperties.has("tokenProvider")) {
      this.restoreSession();
    }

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
      startExpanded: this.startExpanded,
    });

    // Apply custom colors
    this.applyCustomColors();

    // Initialize API service. Auth is read at request time so a `tokenProvider`
    // assigned after the element mounts is still picked up.
    this.apiService = new ApiService(this.config.backendUrl, () =>
      resolveAuthToken(this.tokenProvider, this.config.apiKey)
    );

    // Auto-open if inline mode
    if (this.config.mode === "inline") {
      this.isOpen = true;
    }

    this.restoreSession();
  }

  /**
   * Restore the persisted transcript, once a credential identifies who it
   * belongs to. This waits rather than restoring at mount because a host
   * normally assigns `tokenProvider` after the element is parsed, and a
   * transcript must never be shown to a different signed-in user.
   */
  private restoreSession(): void {
    if (this.sessionRestored) return;

    void (async () => {
      let identity: string;
      try {
        identity = await this.currentIdentity();
      } catch {
        // No credential yet. A later `tokenProvider` assignment retries.
        return;
      }

      this.sessionRestored = true;

      const stored = loadSession(identity);
      if (!stored) return;
      this.chatSessionId = stored.sessionId;
      this.messages = stored.messages;
      // A response that still runs, e.g. one waiting for a decision, shows
      // again, even when the page closed before it saved any of it.
      await this.resumeStream(stored.sessionId);
    })();
  }

  /** Who the current credential represents; scopes the stored transcript. */
  private async currentIdentity(): Promise<string> {
    return deriveCredentialIdentity(
      await resolveAuthToken(this.tokenProvider, this.config.apiKey)
    );
  }

  private applyCustomColors() {
    // Primary color (buttons, accents)
    if (this.config.primaryColor) {
      this.style.setProperty("--theme-primary-05", this.config.primaryColor);
      this.style.setProperty(
        "--theme-primary-06",
        this.adjustBrightness(this.config.primaryColor, -10)
      );
    }

    // Background color
    if (this.config.backgroundColor) {
      this.style.setProperty(
        "--background-neutral-00",
        this.config.backgroundColor
      );
      this.style.setProperty(
        "--background-neutral-03",
        this.adjustBrightness(this.config.backgroundColor, -10)
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
    this.submittingApprovals = new Set();
    this.failedApprovals = new Set();
    this.localApprovalStatuses = new Map();
    this.documentMap.clear();
    this.citationMap.clear();
    clearSession();
  }

  /**
   * Render markdown content safely.
   * Strips [[n]](url) citation links before markdown parsing so they render
   * as plain [n] text references. Citation badges are rendered separately.
   * Renumbers citations to sequential display numbers (1, 2, 3...).
   */
  private renderMarkdown(content: string, citations?: ResolvedCitation[]) {
    try {
      let stripped = content;
      if (this.config.includeCitations) {
        if (citations?.length) {
          // Build a map from backend citation number → sequential display number
          const displayMap = new Map<number, number>();
          citations.forEach((c, i) => displayMap.set(c.citation_number, i + 1));

          // Replace [[n]](url) with superscript-style display number
          stripped = stripped.replace(
            /\[\[(\d+)\]\]\([^)]*\)/g,
            (_match, num) => {
              const displayNum = displayMap.get(Number(num));
              return displayNum ? `<sup>[${displayNum}]</sup>` : "";
            }
          );
        } else {
          // Still streaming or no citations resolved yet — strip raw links
          stripped = stripped.replace(/\[\[(\d+)\]\]\([^)]*\)/g, "");
        }
      }
      const htmlContent = marked.parse(stripped, { async: false }) as string;
      const sanitizedHTML = DOMPurify.sanitize(htmlContent, {
        ADD_TAGS: ["sup"],
      });
      return unsafeHTML(sanitizedHTML);
    } catch (err) {
      console.error("Failed to parse markdown:", err);
      return content; // Fallback to plain text
    }
  }

  private static readonly CITATIONS_COLLAPSED_COUNT = 1;

  /**
   * Render a single citation badge.
   */
  private renderCitationBadge(
    c: ResolvedCitation,
    displayNum: number
  ): TemplateResult {
    const title = c.semantic_identifier || "Source";
    const safeHref =
      c.link && /^https?:\/\//i.test(c.link) ? c.link : undefined;
    return safeHref
      ? html`<a
          class="citation-badge"
          href=${safeHref}
          target="_blank"
          rel="noopener noreferrer"
          title=${title}
          ><span class="citation-num">${displayNum}</span
          ><span class="citation-title">${title}</span></a
        >`
      : html`<span class="citation-badge" title=${title}
          ><span class="citation-num">${displayNum}</span
          ><span class="citation-title">${title}</span></span
        >`;
  }

  /**
   * Toggle expanded state for a citation list.
   */
  private toggleCitationExpand(e: Event): void {
    const container = (e.target as HTMLElement).closest(".citation-list");
    if (container) {
      container.classList.toggle("expanded");
    }
  }

  /**
   * Render citation badges for a message.
   * Shows first 3 inline, collapses the rest behind a "+N more" toggle.
   */
  private renderCitations(
    citations?: ResolvedCitation[]
  ): string | TemplateResult {
    if (!citations?.length) return "";
    const limit = OnyxChatWidget.CITATIONS_COLLAPSED_COUNT;
    const visible = citations.slice(0, limit);
    const overflow = citations.slice(limit);

    return html`
      <div class="citation-list">
        ${visible.map((c, i) => this.renderCitationBadge(c, i + 1))}
        ${
          overflow.length > 0
            ? html`
                <button
                  class="citation-more"
                  @click=${this.toggleCitationExpand}
                >
                  +${overflow.length} more
                </button>
                <div class="citation-overflow">
                  ${overflow.map((c, i) =>
                    this.renderCitationBadge(c, limit + i + 1)
                  )}
                </div>
              `
            : ""
        }
      </div>
    `;
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
    // Shadow DOM retargets `e.target` to the host element, so page-level
    // handlers that let keys through only for text fields (e.g. ones that
    // block Backspace navigation) would cancel typing here. Escape still
    // propagates so the host page can close its overlays.
    if (e.key !== "Escape") {
      e.stopPropagation();
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      this.sendMessage();
    }
  }

  /** The request that still waits for this user, if any. */
  private get pendingApproval(): ApprovalEntry | null {
    return findPendingApproval(this.messages, this.localApprovalStatuses);
  }

  /** Brings a waiting card into view and focuses its first decision. */
  private pointAtApproval(approvalId: string) {
    const card = this.shadowRoot?.querySelector<HTMLElement>(
      `[data-approval-id="${CSS.escape(approvalId)}"]`
    );
    if (!card) return;
    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
    card.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "center",
    });
    card.querySelector<HTMLButtonElement>(".approval-button")?.focus({
      preventScroll: true,
    });
  }

  private async decideApproval(
    request: ToolApprovalRequest,
    decision: ApprovalDecision
  ) {
    const id = request.approval_id;
    if (this.submittingApprovals.has(id)) return;
    this.submittingApprovals = new Set(this.submittingApprovals).add(id);
    const failed = new Set(this.failedApprovals);
    failed.delete(id);
    this.failedApprovals = failed;
    let status: ApprovalStatus | null = null;
    try {
      const result = await this.apiService.submitApprovalDecision(
        id,
        decision
      );
      // 404 or 409: the request no longer waits for a decision.
      status = result === "closed" ? "closed" : decidedStatus(result);
    } catch (err) {
      console.error("Failed to submit approval decision:", err);
      this.failedApprovals = new Set(this.failedApprovals).add(id);
    } finally {
      const submitting = new Set(this.submittingApprovals);
      submitting.delete(id);
      this.submittingApprovals = submitting;
    }
    if (status === null) return;
    // The decided status shows at once; the resolution packet confirms it.
    this.localApprovalStatuses = new Map(this.localApprovalStatuses).set(
      id,
      status
    );
    // The focused button is gone, so focus moves on.
    if (!this.isConnected) return;
    await this.updateComplete;
    const next = this.pendingApproval;
    if (next) {
      this.pointAtApproval(next.request.approval_id);
    } else {
      this.shadowRoot?.querySelector<HTMLInputElement>(".input")?.focus();
    }
  }

  private async sendMessage() {
    const message = this.inputValue.trim();
    if (!message || this.isLoading) return;
    // The draft stays; the run waits for the user's decision first.
    const pending = this.pendingApproval;
    if (pending) {
      this.pointAtApproval(pending.request.approval_id);
      return;
    }
    if (this.isStreaming) return;

    const controller = new AbortController();
    this.abortController = controller;
    const stillOurs = () =>
      this.abortController === controller && !controller.signal.aborted;
    let sentSessionId: string | undefined;
    let acknowledged = false;
    // Set when the response runs on without this stream: the server reports a
    // waiting request this widget does not show, or the stream ended first.
    let reattach = false;
    const userMessage: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: "user",
      content: message,
      timestamp: Date.now(),
    };

    try {
      this.isStreaming = true;
      this.error = undefined;
      if (this.chatSessionId) {
        await this.apiService.waitForSessionIdle(
          this.chatSessionId,
          controller.signal,
          () => {
            if (stillOurs())
              this.streamingStatus =
                "Waiting to confirm that this conversation is ready.";
          }
        );
      }
      if (!stillOurs()) return;

      // Create session if needed
      if (!this.chatSessionId) {
        this.isLoading = true;
        const sessionId = await this.apiService.createChatSession(
          this.config.agentId
        );
        if (!stillOurs()) return;
        this.chatSessionId = sessionId;
        this.isLoading = false;
      }

      // Resolved once per send, so every persisted transcript is tagged with
      // the user who actually produced it.
      const identity = await this.currentIdentity();
      if (!stillOurs()) return;
      this.inputValue = "";
      this.error = undefined;
      this.streamingStatus = "";
      this.messages = [...this.messages, userMessage];

      // Get parent message ID (last assistant message with a numeric ID from backend)
      const parentMessage = [...this.messages]
        .reverse()
        .find((m) => m.role === "assistant" && typeof m.id === "number");
      const parentMessageId =
        parentMessage && typeof parentMessage.id === "number"
          ? parentMessage.id
          : null;

      sentSessionId = this.chatSessionId;
      await this.followStream(
        this.apiService.streamMessage({
          message,
          chatSessionId: this.chatSessionId,
          parentMessageId,
          signal: controller.signal,
          includeCitations: this.config.includeCitations,
        }),
        sentSessionId,
        identity,
        stillOurs,
        ({ userMessageId }) => {
          acknowledged = true;
          if (userMessageId === null) return;
          // Create new array to trigger reactivity
          this.messages = this.messages.map((m) =>
            m.id === userMessage.id ? { ...m, id: userMessageId } : m
          );
        }
      );
      reattach = this.messages.some((m) => m.isStreaming);
    } catch (err: unknown) {
      if (!stillOurs()) return;
      console.error("Failed to send message:", err);
      if (!(err instanceof Error && err.name === "AbortError")) {
        const blocked =
          err instanceof ApiError &&
          err.errorCode === APPROVAL_PENDING_ERROR_CODE;
        reattach = blocked || acknowledged;
        this.error = blocked
          ? "This chat waits for your decision on a tool request. Your message was not sent."
          : err instanceof Error
            ? err.message
            : "Failed to send message";
        if (!acknowledged) {
          this.messages = this.messages.filter(
            (item) => item.id !== userMessage.id
          );
          if (!this.inputValue) this.inputValue = message;
        }
      }
    } finally {
      // A waiting response keeps the session busy until the user decides.
      if (stillOurs() && sentSessionId && !reattach) {
        try {
          await this.apiService.waitForSessionIdle(
            sentSessionId,
            controller.signal,
            () => {
              if (stillOurs())
                this.streamingStatus =
                  "Waiting to confirm that this conversation is ready.";
            }
          );
        } catch (error) {
          if (
            stillOurs() &&
            !(error instanceof Error && error.name === "AbortError")
          ) {
            this.error ??=
              error instanceof Error
                ? error.message
                : "Cannot confirm chat readiness";
          }
        }
      }
      if (this.abortController === controller) {
        this.isStreaming = false;
        this.isLoading = false;
        this.streamingStatus = "";
        this.abortController = undefined;
      }
    }
    if (reattach && sentSessionId && this.abortController === undefined) {
      await this.resumeStream(sentSessionId);
    }
  }

  /**
   * Shows the session's running response again, so a request that waits for a
   * decision can be decided after a reload, a blocked send, or a lost stream.
   */
  private async resumeStream(sessionId: string) {
    if (this.abortController) return;
    const controller = new AbortController();
    this.abortController = controller;
    const stillOurs = () =>
      this.abortController === controller && !controller.signal.aborted;
    this.isStreaming = true;
    try {
      const identity = await this.currentIdentity();
      if (!stillOurs()) return;
      await this.followStream(
        this.apiService.resumeStream(sessionId, controller.signal),
        sessionId,
        identity,
        stillOurs,
        () => {}
      );
      if (!stillOurs()) return;
      // The server can still save the turn after its stream ends.
      await this.apiService.waitForSessionIdle(
        sessionId,
        controller.signal,
        () => {
          if (stillOurs())
            this.streamingStatus =
              "Waiting to confirm that this conversation is ready.";
        }
      );
      // The replay ended before the response did: there was no replay (a 404,
      // e.g. the run finished while the page was closed), or the replay
      // buffer ended early. The server's saved copy finishes the response.
      // On a failure the snapshot stays unfinished, so the next load tries
      // again.
      if (stillOurs() && this.messages.some((message) => message.isStreaming)) {
        const session = await this.apiService.getChatSession(
          sessionId,
          controller.signal
        );
        if (!stillOurs()) return;
        const assistantIds = session.messages
          .filter((message) => message.message_type === "assistant")
          .map((message) => message.message_id);
        for (const message of this.messages) {
          if (!message.isStreaming || typeof message.id !== "number") continue;
          const replay = session.packets[assistantIds.indexOf(message.id)];
          if (!replay) continue;
          const assistantMessageId = message.id;
          await this.followStream(
            (async function* (): AsyncGenerator<Packet, void, unknown> {
              yield {
                obj: {
                  user_message_id: null,
                  reserved_assistant_message_id: assistantMessageId,
                },
              };
              yield* replay;
            })(),
            sessionId,
            identity,
            stillOurs,
            () => {}
          );
          if (!stillOurs()) return;
        }
        // A response the server has no saved copy of keeps its snapshot.
        this.messages = this.messages.map((message) =>
          message.isStreaming ? { ...message, isStreaming: false } : message
        );
        saveSession(sessionId, this.messages, identity);
      }
    } catch (err: unknown) {
      if (stillOurs() && !(err instanceof Error && err.name === "AbortError")) {
        console.error("Failed to resume the response:", err);
        this.error =
          err instanceof Error ? err.message : "Failed to resume the response";
      }
    } finally {
      if (this.abortController === controller) {
        this.isStreaming = false;
        this.streamingStatus = "";
        this.abortController = undefined;
      }
    }
  }

  /** Applies a response stream to the transcript and persists it. */
  private async followStream(
    packets: AsyncGenerator<Packet, void, unknown>,
    sessionId: string,
    identity: string,
    stillOurs: () => boolean,
    onMessageIds: (ids: MessageIDs) => void
  ) {
    let currentMessage: ChatMessage | null = null;
    let assistantMessageId: number | null = null;

    for await (const packet of packets) {
      if (!stillOurs()) return;
      const result = processPacket(packet, currentMessage);

      // Capture message IDs from backend
      if (result.messageIds) {
        onMessageIds(result.messageIds);
        // Store assistant message ID to apply when message is created
        assistantMessageId = result.messageIds.assistantMessageId;
      }

      // Update status if provided
      if (result.status !== undefined) {
        this.streamingStatus = result.status;
      }

      // Accumulate document metadata for citation resolution
      if (result.documents) {
        for (const doc of result.documents) {
          this.documentMap.set(doc.document_id, doc);
        }
      }

      // Accumulate citation mappings for the current message
      if (result.citation) {
        this.citationMap.set(
          result.citation.citation_number,
          result.citation.document_id
        );
      }

      // The server outcome replaces this widget's decision.
      if (
        "type" in packet.obj &&
        packet.obj.type === "tool_approval_resolved" &&
        readOutcome(packet.obj.outcome) !== null &&
        this.localApprovalStatuses.has(packet.obj.approval_id)
      ) {
        const statuses = new Map(this.localApprovalStatuses);
        statuses.delete(packet.obj.approval_id);
        this.localApprovalStatuses = statuses;
      }

      if (result.message) {
        // Reset per-message citation state when a new message starts
        if (
          result.message.isStreaming &&
          result.message.content === "" &&
          currentMessage === null
        ) {
          this.citationMap.clear();
        }

        currentMessage = result.message;

        // Apply the backend message ID if we have it and message doesn't have a numeric ID yet
        if (
          assistantMessageId !== null &&
          typeof currentMessage.id !== "number"
        ) {
          currentMessage.id = assistantMessageId;
        }

        // When message is complete, resolve citations and attach to message
        if (!currentMessage.isStreaming && this.citationMap.size > 0) {
          const resolved: ResolvedCitation[] = [];
          for (const [citNum, docId] of this.citationMap) {
            const doc = this.documentMap.get(docId);
            resolved.push({
              citation_number: citNum,
              document_id: docId,
              semantic_identifier: doc?.semantic_identifier,
              link: doc?.link ?? undefined,
            });
          }
          resolved.sort((a, b) => a.citation_number - b.citation_number);
          currentMessage = { ...currentMessage, citations: resolved };
        }

        // Update or add message
        const existingIndex = this.messages.findIndex(
          (m) => m.id === currentMessage?.id
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

        // Clear streaming state when message is complete. Persist then, and
        // when a request waits, so a reload can show it again.
        if (!currentMessage.isStreaming) {
          this.streamingStatus = "";
        }
        if (
          !currentMessage.isStreaming ||
          ("type" in packet.obj && packet.obj.type === "tool_approval_request")
        ) {
          saveSession(sessionId, this.messages, identity);
        }
      }
    }
  }

  render() {
    const showContainer = this.config.mode === "inline" || this.isOpen;
    const hasMessages = this.messages.length > 0 || this.isStreaming;
    const isCompactInline =
      this.config.mode === "inline" &&
      !this.config.startExpanded &&
      !hasMessages &&
      !this.error;

    return html`
      ${
        this.config.mode === "launcher"
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
          : ""
      }
      ${
        showContainer
          ? html`
              <div
                class="container ${
                  this.config.mode === "inline" ? "inline" : ""
                } ${isCompactInline ? "compact" : ""}"
              >
                ${
                  isCompactInline
                    ? this.renderCompactInput()
                    : html`
                        ${this.renderHeader()} ${this.renderMessages()}
                        ${this.renderInput()}
                      `
                }
              </div>
            `
          : ""
      }
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
          ${
            this.config.mode === "launcher"
              ? html`
                  <button
                    class="icon-button"
                    @click=${this.close}
                    title="Close"
                  >
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
              : ""
          }
        </div>
      </div>
    `;
  }

  private renderMessages() {
    // Check if there's a streaming message with content
    const hasStreamingContent = this.messages.some(
      (m) => m.role === "assistant" && m.isStreaming && m.content.length > 0
    );
    // Show ellipsis only when: streaming AND (has status text OR no content yet)
    // AND no card waits for the user
    const showEllipsis =
      this.isStreaming &&
      !this.pendingApproval &&
      (this.streamingStatus || !hasStreamingContent);

    return html`
      <div class="disclaimer">
        Responses are generated by AI and may be inaccurate
      </div>
      <div class="messages">
        ${this.error ? html` <div class="error">${this.error}</div> ` : ""}
        ${this.messages.map(
          (msg) => html`
            <div class="message ${msg.role}">
              ${
                msg.role === "assistant" &&
                !msg.content &&
                msg.approvals?.length
                  ? ""
                  : html`<div class="message-bubble">
                      ${
                        msg.role === "assistant"
                          ? html`${this.renderMarkdown(
                              msg.content,
                              msg.citations
                            )}${this.renderCitations(msg.citations)}`
                          : msg.content
                      }
                    </div>`
              }
              ${(msg.approvals ?? []).map((entry) =>
                this.renderApproval(
                  entry,
                  approvalStatus(
                    entry,
                    this.localApprovalStatuses.get(entry.request.approval_id),
                    !msg.isStreaming
                  )
                )
              )}
            </div>
          `
        )}
        ${
          showEllipsis
            ? html`
                <div class="message assistant">
                  <div class="message-bubble">
                    <div class="status-container">
                      <div class="typing-indicator">
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                      </div>
                      ${
                        this.streamingStatus
                          ? html`
                              <span class="status-text"
                                >${this.streamingStatus}</span
                              >
                            `
                          : ""
                      }
                    </div>
                  </div>
                </div>
              `
            : ""
        }
      </div>
    `;
  }

  /** A waiting request shows its arguments and decisions; a decided one, one line. */
  private renderApproval(entry: ApprovalEntry, status: ApprovalStatus) {
    const { request } = entry;
    const name = request.display_name || request.tool_name;
    const record = approvalRecord(status, name);
    const title = `Approval requested: ${name}`;
    const submitting = this.submittingApprovals.has(request.approval_id);
    const deadline = approvalDeadline(request.expires_at);
    const rows = argumentRows(request.arguments);

    return html`
      <div class="approval" data-approval-id=${request.approval_id}>
        <p class="sr-only" role="status">${record ?? title}</p>
        ${
          record !== null
            ? html`<div class="approval-record" aria-hidden="true">
                ${
                  status === "approved" || status === "approvedForSession"
                    ? ICON_CHECK
                    : status === "rejected" || status === "disabled"
                      ? ICON_X
                      : ICON_CLOCK
                }
                <span title=${record}>${record}</span>
              </div>`
            : html`<div class="approval-card">
                <div class="approval-header">
                  <span class="approval-spinner" aria-hidden="true"
                    >${ICON_LOADER}</span
                  >
                  <span class="approval-title" title=${title}>${title}</span>
                  ${
                    deadline
                      ? html`<span class="approval-deadline">${deadline}</span>`
                      : ""
                  }
                </div>
                <div class="approval-body">
                  ${
                    rows.length === 0
                      ? html`<p class="approval-empty">No payload.</p>`
                      : html`<dl class="approval-args">
                          ${rows.map(
                            (row) => html`
                              <dt title=${row.key}>${row.key}</dt>
                              <dd class=${row.mono ? "mono" : ""}>
                                ${
                                  row.preview === null
                                    ? html`<span class="arg-value"
                                        >${row.text}</span
                                      >`
                                    : html`<span class="arg-value arg-preview"
                                          >${row.preview}</span
                                        ><span class="arg-value arg-full"
                                          >${row.text}</span
                                        ><button
                                          class="arg-toggle"
                                          aria-expanded="false"
                                          @click=${this.toggleArgument}
                                        >
                                          <span class="arg-more">Show more</span
                                          ><span class="arg-less">Show less</span>
                                        </button>`
                                }
                              </dd>
                            `
                          )}
                        </dl>`
                  }
                  ${
                    this.failedApprovals.has(request.approval_id)
                      ? html`<p class="approval-error" role="alert">
                          Could not submit your decision. Try again.
                        </p>`
                      : ""
                  }
                </div>
                <div class="approval-actions">
                  <button
                    class="approval-button primary"
                    ?disabled=${submitting}
                    @click=${() =>
                      this.decideApproval(request, "approve_once")}
                  >
                    Approve once
                  </button>
                  <button
                    class="approval-button"
                    ?disabled=${submitting}
                    title="Approve now and run this tool without asking again for the rest of this chat"
                    @click=${() =>
                      this.decideApproval(request, "approve_session")}
                  >
                    Approve for this chat
                  </button>
                  <button
                    class="approval-button"
                    ?disabled=${submitting}
                    @click=${() => this.decideApproval(request, "reject")}
                  >
                    Reject
                  </button>
                </div>
              </div>`
        }
      </div>
    `;
  }

  /** Expands or collapses a long argument value. */
  private toggleArgument(e: Event): void {
    const button = e.currentTarget as HTMLElement;
    const expanded = button.closest("dd")?.classList.toggle("expanded");
    button.setAttribute("aria-expanded", String(Boolean(expanded)));
  }

  /** Shown under the composer while a request waits for the user. */
  private renderApprovalNotice() {
    return this.pendingApproval
      ? html`<div class="approval-notice">
          Approve or reject the tool request above to continue. Your message
          stays here.
        </div>`
      : "";
  }

  private renderInput() {
    const pending = this.pendingApproval !== null;
    const inputDisabled = this.isLoading || (this.isStreaming && !pending);
    return html`
      <div class="input-wrapper">
        ${this.renderApprovalNotice()}
        <div class="input-container">
          <input
            class="input"
            type="text"
            .value=${this.inputValue}
            @input=${this.handleInput}
            @keydown=${this.handleKeyDown}
            placeholder="Type your message..."
            ?disabled=${inputDisabled}
          />
          <button
            class="send-button"
            @click=${this.sendMessage}
            ?disabled=${!this.inputValue.trim() || inputDisabled}
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
          ?disabled=${
            !this.inputValue.trim() || this.isLoading || this.isStreaming
          }
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
