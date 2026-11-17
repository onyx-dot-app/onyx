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
  ApprovalDecisionResponse,
  ChatSessionStatus,
  ChatStream,
  Packet,
  SearchDocument,
  ResolvedCitation,
  StreamCursor,
  ToolApprovalRequest,
} from "./types/api-types";
import {
  resolveConfig,
  resolveAuthToken,
  deriveCredentialIdentity,
} from "./config/config";
import { theme } from "./styles/theme";
import { widgetStyles } from "./styles/widget-styles";
import {
  ApiError,
  ApiService,
  READINESS_POLL_INTERVAL_MS,
  ResumeEnd,
  pause,
} from "./services/api-service";
import {
  APPROVAL_PENDING_ERROR_CODE,
  ApprovalDecision,
  ApprovalEntry,
  approvalStatus,
  decidedStatus,
  findPendingApproval,
  LocalApproval,
  readOutcome,
} from "./services/approvals";
import { renderApprovalCard } from "./services/approval-card";
import {
  MessageIDs,
  processPacket,
  StreamErrorPacket,
} from "./services/stream-parser";
import { saveSession, loadSession, clearSession } from "./utils/storage";
import { DEFAULT_LOGO } from "./assets/logo";

let linkHookAdded = false;

/** Sanitizes answer HTML; its links open in a new tab so the visitor keeps the host page. */
function sanitizeAnswerHtml(dirty: string): string {
  // Added on first use: DOMPurify has no hooks API until it runs with a DOM
  if (!linkHookAdded) {
    DOMPurify.addHook("afterSanitizeAttributes", (node) => {
      if (node.tagName === "A") {
        node.setAttribute("target", "_blank");
        node.setAttribute("rel", "noopener noreferrer");
      }
    });
    linkHookAdded = true;
  }
  return DOMPurify.sanitize(dirty, { ADD_TAGS: ["sup"] });
}

/** What a followed stream applied, and where a reattach continues from. */
interface StreamFollow {
  message: ChatMessage | null;
  // The saved ids of the turn's question and answer, from its first packet
  userMessageId: number | null;
  assistantMessageId: number | null;
  streamId: number | null;
  cursor: number;
  // The message as of `cursor`; packets after it arrive again on a reattach
  messageAtCursor: ChatMessage | null;
  // The response's stop or error arrived
  ended: boolean;
}

function newFollow(streamId: number | null): StreamFollow {
  return {
    message: null,
    userMessageId: null,
    assistantMessageId: null,
    streamId,
    cursor: 0,
    messageAtCursor: null,
    ended: false,
  };
}

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
  // This widget's state for each request, by approval id, until the server
  // resolves it
  @state() private localApprovals = new Map<string, LocalApproval>();
  // Expanded argument values, as `[approval id, key]` JSON, and cards that
  // show all their rows, as `[approval id]` JSON
  @state() private expandedArguments: ReadonlySet<string> = new Set();

  private config!: WidgetConfig;
  private apiService!: ApiService;
  private sessionRestored = false;
  private abortController?: AbortController;
  // Citation state — plain fields (not @state) since Map mutations don't trigger Lit re-renders
  private documentMap = new Map<string, SearchDocument>();
  private citationMap = new Map<number, string>();
  // A continuation a decision named while another stream was followed
  private continuationStreamId: number | null = null;
  // A decision with no continuation landed while a follow ran; the follow
  // reads the status again before it ends
  private statusRecheck = false;
  // Answers that a status read named as the latest and the transcript
  // lacks: they can start and finish between two reads. The next session
  // load shows them.
  private unseenAnswerIds = new Set<number>();
  // The `approvals_version` of the requests the transcript shows, from the
  // last session load; "" before any load, the version of a chat with no
  // requests. A change replays the saved session, the one source of
  // background agent requests and their outcomes
  private approvalsVersion = "";
  private approvalsChanged = false;

  /** Notes a status read's latest answer when the transcript lacks it. */
  private noteLatestAnswer(status: ChatSessionStatus) {
    const latest = status.latest_response_id;
    if (latest !== null && !this.messages.some((m) => m.id === latest))
      this.unseenAnswerIds.add(latest);
  }

  /** Notes a status read's version when it differs from the baseline. */
  private noteApprovalsVersion(status: ChatSessionStatus) {
    const version = status.approvals_version;
    if (version === null || version === this.approvalsVersion) return;
    this.approvalsVersion = version;
    this.approvalsChanged = true;
  }

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
      // The stored transcript can predate request outcomes and later turns,
      // so the load replays the answers that hold approval requests or that
      // the transcript lacks.
      this.approvalsChanged = true;
      // A response that still runs or waits for a decision shows again, even
      // when the page closed before it saved any of it.
      await this.resumeStream(stored.sessionId, { streamId: null });
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
    this.localApprovals = new Map();
    this.expandedArguments = new Set();
    this.continuationStreamId = null;
    this.statusRecheck = false;
    this.unseenAnswerIds = new Set();
    this.approvalsVersion = "";
    this.approvalsChanged = false;
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
      return unsafeHTML(sanitizeAnswerHtml(htmlContent));
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
    return findPendingApproval(this.messages, this.localApprovals);
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
    if (this.localApprovals.get(id) === "submitting") return;
    // A reset or another chat can open while the request runs; the result
    // then changes nothing in the chat that is open.
    const sessionId = this.chatSessionId;
    this.localApprovals = new Map(this.localApprovals).set(id, "submitting");
    let result: ApprovalDecisionResponse | "closed";
    try {
      result = await this.apiService.submitApprovalDecision(id, decision);
    } catch (err) {
      console.error("Failed to submit approval decision:", err);
      if (this.chatSessionId !== sessionId) return;
      this.localApprovals = new Map(this.localApprovals).set(id, "failed");
      return;
    }
    if (this.chatSessionId !== sessionId) return;
    // The decided status shows until the server's resolution arrives.
    this.localApprovals = new Map(this.localApprovals).set(
      id,
      result === "closed" ? "closed" : decidedStatus(result)
    );
    // Follow the continuation the server names. A running follow reads it
    // after its current stream; with no continuation it reads the status
    // again before it ends. A request that no longer waits (404 or 409)
    // follows the session's status, and the saved session shows its
    // outcome. A background agent continues without a stream, so its later
    // requests come from the saved session.
    // The last root decision with no continuation landed while another turn
    // held the chat: the follow reads the current stream, then each stream
    // the status reports, and the saved session when the session is idle.
    const continuation = result === "closed" ? null : result.continuation;
    if (sessionId && !this.abortController) {
      if (continuation) {
        void this.resumeStream(sessionId, {
          streamId: continuation.stream_id,
        });
      } else if (result === "closed" || request.agent_name) {
        void this.resumeStream(sessionId, null);
      } else if (decision === "approve_session") {
        // The server also approved this chat's other requests for the tool,
        // which only the saved session shows.
        this.approvalsChanged = true;
        void this.resumeStream(sessionId, { streamId: null });
      } else if (this.pendingApproval === null) {
        void this.resumeStream(sessionId, { streamId: null });
      }
    } else if (continuation) {
      this.continuationStreamId = continuation.stream_id;
    } else {
      this.statusRecheck = true;
    }
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
    if (this.isStreaming) {
      // The draft stays while a followed response holds the chat.
      const pending = this.pendingApproval;
      if (pending) this.pointAtApproval(pending.request.approval_id);
      return;
    }

    // A send takes over from a status poll for background agents; its own
    // follow reads the status after its stream.
    this.abortController?.abort();
    const controller = new AbortController();
    this.abortController = controller;
    const stillOurs = () =>
      this.abortController === controller && !controller.signal.aborted;
    let sentSessionId: string | undefined;
    const follow = newFollow(null);
    // The server refused the send while a request waits for a decision
    let blocked = false;
    const userMessage: ChatMessage = {
      id: `msg-${Date.now()}`,
      role: "user",
      content: message,
      timestamp: Date.now(),
    };

    try {
      this.isStreaming = true;
      this.error = undefined;
      if (!this.chatSessionId) {
        this.isLoading = true;
        const sessionId = await this.apiService.createChatSession(
          this.config.agentId
        );
        if (!stillOurs()) return;
        this.chatSessionId = sessionId;
        this.isLoading = false;
      }
      const status = await this.apiService.waitForSessionIdle(
        this.chatSessionId,
        controller.signal,
        () => {
          if (stillOurs())
            this.streamingStatus =
              "Waiting to confirm that this conversation is ready.";
        }
      );
      if (!stillOurs()) return;
      // A new chat shows no requests; a background agent can ask before
      // this read, which then reports a version other than "".
      this.noteApprovalsVersion(status);
      this.noteLatestAnswer(status);

      // Resolved once per send, so every persisted transcript is tagged with
      // the user who actually produced it.
      const identity = await this.currentIdentity();
      if (!stillOurs()) return;
      // The latest saved answer can have finished after this widget's last
      // status read, for example an answer to an agent's result; the send
      // goes under it, so the transcript shows it first.
      if (
        [...this.unseenAnswerIds].some(
          (answerId) => !this.messages.some((m) => m.id === answerId)
        ) &&
        !(await this.recoverFromSavedSession(
          this.chatSessionId,
          identity,
          stillOurs,
          controller.signal,
          null,
          true
        ))
      )
        return;
      this.inputValue = "";
      this.error = undefined;
      this.streamingStatus = "";
      this.messages = [...this.messages, userMessage];

      // The parent is the latest saved answer: the backend treats a question
      // as the parent of a regeneration, not of a new question.
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
        follow,
        ({ userMessageId, assistantMessageId }) => {
          // The sent response's stream id is its answer's id.
          follow.streamId = assistantMessageId;
          if (userMessageId === null) return;
          // Create new array to trigger reactivity
          this.messages = this.messages.map((m) =>
            m.id === userMessage.id ? { ...m, id: userMessageId } : m
          );
        }
      );
    } catch (err: unknown) {
      if (!stillOurs()) return;
      console.error("Failed to send message:", err);
      if (!(err instanceof Error && err.name === "AbortError")) {
        blocked =
          err instanceof ApiError &&
          err.errorCode === APPROVAL_PENDING_ERROR_CODE;
        this.error = blocked
          ? "Approve or reject the pending tool calls first."
          : err instanceof Error
            ? err.message
            : "Failed to send message";
        if (follow.assistantMessageId === null) {
          this.messages = this.messages.filter(
            (item) => item.id !== userMessage.id
          );
          if (!this.inputValue) this.inputValue = message;
        }
      }
    } finally {
      if (this.abortController === controller) {
        this.isStreaming = false;
        this.isLoading = false;
        this.streamingStatus = "";
        this.abortController = undefined;
      }
    }
    if (!sentSessionId || controller.signal.aborted || this.abortController)
      return;
    if (blocked) {
      // The saved session shows the waiting card.
      this.approvalsChanged = true;
      await this.resumeStream(sentSessionId, null);
      const pending = this.pendingApproval;
      if (!pending || !this.isConnected) return;
      await this.updateComplete;
      this.pointAtApproval(pending.request.approval_id);
      return;
    }
    // An unacknowledged send left no stream; only the idle wait remains.
    if (follow.assistantMessageId === null) follow.ended = true;
    await this.resumeStream(sentSessionId, { sent: follow });
  }

  /**
   * The one path that follows the session's response: after a send, a
   * reload, a blocked send, or a decision. `start` is the send's stream,
   * already applied; a stream to read from its start, such as the
   * continuation a decision names (null: the current stream); or null to
   * start at the session's status.
   *
   * A stream that ends before its stop is attached again from its last
   * cursor while the session still runs it. After a stop, a new stream that
   * the status reports is followed from its start. After a stop for
   * decisions, the follow takes the continuation a decision named meanwhile,
   * or a new stream that the status reports for the same response.
   *
   * When no stream is left, the saved session shows what the streams did
   * not. While background agents run, the status is read every poll
   * interval: a changed approvals version replays the saved session, and a
   * new stream is followed.
   */
  private async resumeStream(
    sessionId: string,
    start: { sent: StreamFollow } | { streamId: number | null } | null
  ) {
    if (this.abortController) return;
    const controller = new AbortController();
    this.abortController = controller;
    const stillOurs = () =>
      this.abortController === controller && !controller.signal.aborted;
    const onUnconfirmed = () => {
      if (stillOurs())
        this.streamingStatus =
          "Waiting to confirm that this conversation is ready.";
    };
    this.isStreaming = true;
    try {
      const identity = await this.currentIdentity();
      if (!stillOurs()) return;
      const sent = start !== null && "sent" in start ? start.sent : null;
      let follow: StreamFollow | null =
        sent ??
        (start !== null && "streamId" in start
          ? newFollow(start.streamId)
          : null);
      let applied = sent !== null;
      // A stream without a replay buffer is never requested again.
      let streamWithoutBuffer: number | null = null;
      // The last stream followed; it does not run again
      let lastStreamId: number | null = null;
      // The sent answer, which the saved session shows when no stream did
      let sentAnswerId = sent?.assistantMessageId ?? null;
      // The saved session can show what the streams of this pass did not
      let recover = true;
      // Server work waits, so the status is read again: background agents
      // run, or queued input or unread agent results can start a turn
      let workWaits = start === null;
      // A follow that starts at the status reads it without a pause.
      let pausesFirst = start !== null;
      for (;;) {
        // The followed response stopped for decisions, and its stream showed
        // it as the server saved it.
        let waitsForDecisions = false;
        while (follow !== null) {
          const current: StreamFollow = follow;
          let end: ResumeEnd | null = null;
          if (!applied) {
            const { streamId, cursor } = current;
            const packets = this.apiService.resumeStream(
              sessionId,
              controller.signal,
              streamId === null ? null : { streamId, cursor }
            );
            try {
              await this.followStream(
                (async function* () {
                  end = yield* packets;
                })(),
                sessionId,
                identity,
                stillOurs,
                current,
                () => {}
              );
            } catch (err: unknown) {
              if (
                !stillOurs() ||
                err instanceof StreamErrorPacket ||
                (err instanceof Error && err.name === "AbortError")
              )
                throw err;
              // A transport failure after the stop loses nothing: the status
              // check after the stop runs as usual.
              if (!current.ended)
                console.warn("The response stream ended early:", err);
            }
          }
          applied = false;
          if (!stillOurs()) return;
          let status: ChatSessionStatus;
          if (current.message?.awaitingApproval) {
            const named = this.continuationStreamId;
            this.continuationStreamId = null;
            if (named !== null && named !== current.streamId) {
              follow = newFollow(named);
              continue;
            }
            // A run that parks continues in a new stream.
            const responseId = current.assistantMessageId;
            status = await this.apiService.waitForSessionIdle(
              sessionId,
              controller.signal,
              onUnconfirmed,
              (stream: ChatStream) =>
                stream.stream_id !== current.streamId &&
                responseId !== null &&
                stream.response_ids.includes(responseId)
            );
            // After the last decision, an idle session finished the response.
            waitsForDecisions =
              !status.is_processing && this.pendingApproval !== null;
          } else if (current.ended) {
            // The server can still save the turn after its stream ends, and
            // another client can start a new response meanwhile.
            const ended = current.streamId;
            status = await this.apiService.waitForSessionIdle(
              sessionId,
              controller.signal,
              onUnconfirmed,
              (stream: ChatStream) =>
                ended !== null &&
                stream.stream_id !== ended &&
                stream.stream_id !== streamWithoutBuffer
            );
          } else {
            // Only a 404 means the buffer is gone; other ends are retried.
            // Before the first cursor the stream id is unknown, so the first
            // stream the status reports gets one attempt.
            if (end === "noBuffer") streamWithoutBuffer = current.streamId;
            await pause(READINESS_POLL_INTERVAL_MS, controller.signal);
            status = await this.apiService.waitForSessionIdle(
              sessionId,
              controller.signal,
              onUnconfirmed,
              (stream: ChatStream) => stream.stream_id !== streamWithoutBuffer
            );
          }
          if (!stillOurs()) return;
          this.noteApprovalsVersion(status);
          this.noteLatestAnswer(status);
          workWaits =
            status.has_active_subagents || status.has_startable_input;
          lastStreamId = current.streamId;
          const next = status.is_processing ? status.current_stream : null;
          if (next === null) {
            follow = null;
          } else if (next.stream_id === current.streamId) {
            current.message = current.messageAtCursor;
          } else {
            follow = newFollow(next.stream_id);
            if (this.continuationStreamId === next.stream_id)
              this.continuationStreamId = null;
          }
        }
        if (
          !(await this.recoverFromSavedSession(
            sessionId,
            identity,
            stillOurs,
            controller.signal,
            sentAnswerId,
            recover && !waitsForDecisions
          ))
        )
          return;
        sentAnswerId = null;
        // A decision made during this pass, for example while the saved
        // session loaded, names a continuation that no stream followed.
        const queued = this.continuationStreamId;
        this.continuationStreamId = null;
        if (queued !== null && queued !== lastStreamId) {
          follow = newFollow(queued);
          continue;
        }
        // A status read from before such a decision can show no running
        // agent and an older approvals version.
        if (this.statusRecheck) {
          this.statusRecheck = false;
          workWaits = true;
        }
        if (!workWaits) return;
        // Waiting work never holds the chat: a send can end this poll. The
        // poll leaves the streaming state alone until it follows a stream.
        this.isStreaming = false;
        this.streamingStatus = "";
        if (pausesFirst)
          await pause(READINESS_POLL_INTERVAL_MS, controller.signal);
        pausesFirst = true;
        const status = await this.apiService.waitForSessionIdle(
          sessionId,
          controller.signal,
          () => {},
          (stream: ChatStream) =>
            stream.stream_id !== streamWithoutBuffer &&
            stream.stream_id !== lastStreamId
        );
        if (!stillOurs()) return;
        this.noteApprovalsVersion(status);
        this.noteLatestAnswer(status);
        workWaits = status.has_active_subagents || status.has_startable_input;
        const next = status.is_processing ? status.current_stream : null;
        if (next !== null) {
          this.isStreaming = true;
          follow = newFollow(next.stream_id);
          if (this.continuationStreamId === next.stream_id)
            this.continuationStreamId = null;
        }
        recover = next !== null || this.unseenAnswerIds.size > 0;
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
        this.continuationStreamId = null;
        this.statusRecheck = false;
      }
    }
  }

  /**
   * Shows from the saved session what this widget's streams did not: a
   * response that ended or stopped for decisions with no replay (a 404,
   * e.g. the run finished while the page was closed) or after its replay
   * buffer ended early, and an answer that started and finished between
   * two status reads. The saved copy finishes the response or shows its
   * waiting requests, and answers or removes a saved question with no
   * answer after it. A
   * changed approvals version replays every saved answer that holds an
   * approval request or that the transcript lacks. On a failure the
   * snapshot stays unfinished and the version change stays pending, so
   * the next load tries again.
   *
   * `recover` lets unfinished or waiting responses, unanswered questions,
   * `sentAnswerId` and answers a status read named load the session; a
   * changed approvals version always does. False when another follow or
   * send took over.
   */
  private async recoverFromSavedSession(
    sessionId: string,
    identity: string,
    stillOurs: () => boolean,
    signal: AbortSignal,
    sentAnswerId: number | null,
    recover: boolean
  ): Promise<boolean> {
    const approvalsChanged = this.approvalsChanged;
    const unanswered = this.messages
      .filter(
        (message, index) =>
          message.role === "user" &&
          this.messages[index + 1]?.role !== "assistant"
      )
      .map((message) => message.id)
      .filter((id): id is number => typeof id === "number");
    const recoverIds = this.messages
      .filter((message) => message.isStreaming || message.awaitingApproval)
      .map((message) => message.id)
      .filter((id): id is number => typeof id === "number");
    for (const answerId of [sentAnswerId, ...this.unseenAnswerIds]) {
      if (
        answerId !== null &&
        !recoverIds.includes(answerId) &&
        !this.messages.some((message) => message.id === answerId)
      )
        recoverIds.push(answerId);
    }
    if (
      !approvalsChanged &&
      !(
        recover &&
        (recoverIds.length > 0 ||
          unanswered.length > 0 ||
          this.messages.some((message) => message.isStreaming))
      )
    )
      return true;
    const session = await this.apiService.getChatSession(
      sessionId,
      signal
    );
    if (!stillOurs()) return false;
    // The load's version is the baseline for the requests it shows.
    if (session.approvals_version !== undefined)
      this.approvalsVersion = session.approvals_version;
    // Packet lists follow every assistant message, on every branch.
    const assistants = session.messages.filter(
      (message) => message.message_type === "assistant"
    );
    // The selected branch runs from the root along each latest child;
    // a message's position on it is its place in the conversation.
    const byId = new Map(
      session.messages.map((message) => [message.message_id, message])
    );
    const savedOrder = new Map<number, number>();
    let onBranch = session.messages.find(
      (message) =>
        message.parent_message == null ||
        !byId.has(message.parent_message)
    );
    while (onBranch && !savedOrder.has(onBranch.message_id)) {
      savedOrder.set(onBranch.message_id, savedOrder.size);
      const child = onBranch.latest_child_message;
      onBranch = child == null ? undefined : byId.get(child);
    }
    for (const questionId of unanswered) {
      const answer = assistants.find(
        (message) =>
          message.parent_message === questionId &&
          savedOrder.has(message.message_id)
      );
      if (!answer) {
        this.messages = this.messages.filter(
          (message) => message.id !== questionId
        );
      } else if (!recoverIds.includes(answer.message_id)) {
        recoverIds.push(answer.message_id);
      }
    }
    if (approvalsChanged) {
      // A background agent's request is saved under the answer that
      // started the agent, which can be any earlier answer. A turn
      // accepted after the transcript was saved is missing from it.
      assistants.forEach((message, index) => {
        if (
          savedOrder.has(message.message_id) &&
          !recoverIds.includes(message.message_id) &&
          (!this.messages.some(
            (shown) => shown.id === message.message_id
          ) ||
            session.packets[index]?.some(
              (packet) =>
                "type" in packet.obj &&
                packet.obj.type === "tool_approval_request"
            ))
        ) {
          recoverIds.push(message.message_id);
        }
      });
    }
    for (const assistantMessageId of recoverIds) {
      const index = assistants.findIndex(
        (message) => message.message_id === assistantMessageId
      );
      const replay = session.packets[index];
      if (!replay) continue;
      const userMessageId = assistants[index]?.parent_message ?? null;
      await this.followStream(
        (async function* (): AsyncGenerator<Packet, void, unknown> {
          yield {
            obj: {
              user_message_id: userMessageId,
              reserved_assistant_message_id: assistantMessageId,
            },
          };
          yield* replay;
        })(),
        sessionId,
        identity,
        stillOurs,
        newFollow(null),
        () => {}
      );
      if (!stillOurs()) return false;
    }
    this.approvalsChanged = false;
    this.unseenAnswerIds = new Set();
    // Recovered turns take their saved place in the conversation, so a
    // later send answers the latest saved turn. A message off the
    // selected branch stays after the message before it.
    let position = -1;
    this.messages = this.messages
      .map((message) => {
        const saved =
          typeof message.id === "number"
            ? savedOrder.get(message.id)
            : undefined;
        if (saved !== undefined) position = saved;
        return { message, position };
      })
      .sort((a, b) => a.position - b.position)
      .map(({ message }) =>
        // A response the server has no saved copy of keeps its snapshot.
        message.isStreaming ? { ...message, isStreaming: false } : message
      );
    saveSession(sessionId, this.messages, identity);
    return true;
  }

  /** Applies a response stream to the transcript and persists it. */
  private async followStream(
    packets: AsyncGenerator<Packet | StreamCursor, void, unknown>,
    sessionId: string,
    identity: string,
    stillOurs: () => boolean,
    follow: StreamFollow,
    onMessageIds: (ids: MessageIDs) => void
  ) {
    for await (const packet of packets) {
      if (!stillOurs()) return;
      if ("next_cursor" in packet) {
        follow.streamId = packet.stream_id;
        follow.cursor = packet.next_cursor;
        follow.messageAtCursor = follow.message;
        continue;
      }
      if (
        "type" in packet.obj &&
        (packet.obj.type === "stop" ||
          packet.obj.type === "overall_stop" ||
          packet.obj.type === "error")
      ) {
        follow.ended = true;
      }
      const result = processPacket(packet, follow.message);

      // Capture message IDs from backend
      if (result.messageIds) {
        onMessageIds(result.messageIds);
        // Store assistant message ID to apply when message is created
        follow.userMessageId = result.messageIds.userMessageId;
        follow.assistantMessageId = result.messageIds.assistantMessageId;
      }

      // A turn accepted before this transcript was saved gets its question
      // back, before its answer.
      const questionId = follow.userMessageId;
      if (
        "type" in packet.obj &&
        packet.obj.type === "user_message" &&
        questionId !== null &&
        !this.messages.some((message) => message.id === questionId)
      ) {
        const question: ChatMessage = {
          id: questionId,
          role: "user",
          content: packet.obj.message,
          timestamp: Date.now(),
        };
        const answerIndex = this.messages.findIndex(
          (message) => message.id === follow.assistantMessageId
        );
        this.messages =
          answerIndex >= 0
            ? [
                ...this.messages.slice(0, answerIndex),
                question,
                ...this.messages.slice(answerIndex),
              ]
            : [...this.messages, question];
        saveSession(sessionId, this.messages, identity);
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
        this.localApprovals.has(packet.obj.approval_id)
      ) {
        const local = new Map(this.localApprovals);
        local.delete(packet.obj.approval_id);
        this.localApprovals = local;
      }

      if (result.message) {
        // Reset per-message citation state when a new message starts
        if (
          result.message.isStreaming &&
          result.message.content === "" &&
          follow.message === null
        ) {
          this.citationMap.clear();
        }

        let currentMessage = result.message;

        // Apply the backend message ID if we have it and message doesn't have a numeric ID yet
        if (
          follow.assistantMessageId !== null &&
          typeof currentMessage.id !== "number"
        ) {
          currentMessage.id = follow.assistantMessageId;
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

        follow.message = currentMessage;

        // Update or add message
        const existingIndex = this.messages.findIndex(
          (m) => m.id === currentMessage.id
        );
        if (existingIndex >= 0) {
          this.messages = [
            ...this.messages.slice(0, existingIndex),
            currentMessage,
            ...this.messages.slice(existingIndex + 1),
          ];
        } else {
          // A new answer follows its question.
          const questionIndex = this.messages.findIndex(
            (m) => m.id === follow.userMessageId
          );
          this.messages =
            questionIndex >= 0
              ? [
                  ...this.messages.slice(0, questionIndex + 1),
                  currentMessage,
                  ...this.messages.slice(questionIndex + 1),
                ]
              : [...this.messages, currentMessage];
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
              ${(msg.approvals ?? []).map((entry) => {
                const local = this.localApprovals.get(
                  entry.request.approval_id
                );
                return renderApprovalCard(entry, approvalStatus(entry, local), {
                  submitting: local === "submitting",
                  failed: local === "failed",
                  expanded: this.expandedArguments,
                  onDecide: (request, decision) =>
                    this.decideApproval(request, decision),
                  onToggle: (id) => {
                    const expanded = new Set(this.expandedArguments);
                    if (!expanded.delete(id)) expanded.add(id);
                    this.expandedArguments = expanded;
                  },
                });
              })}
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

  private renderInput() {
    const pending = this.pendingApproval !== null;
    const inputDisabled = this.isLoading || (this.isStreaming && !pending);
    return html`
      <div class="input-wrapper">
        ${
          pending
            ? html`<div class="approval-notice">
                Approve or reject the tool request above to continue. Your
                message stays here.
              </div>`
            : ""
        }
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
