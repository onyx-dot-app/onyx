import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  Button,
  CompactMarkdown,
  type CompactMarkdownProps,
  InputTypeIn,
  LineItemButton,
  Text,
} from "@opal/components";
import { Section } from "@opal/layouts";
import { mount } from "@/lib/mount";
import { hasPrimaryModifier, primaryShortcut } from "@/lib/platform";
import {
  ask,
  errorMessage,
  hideLauncher,
  openChatInMain,
  openExternal,
  search,
  type Citation,
  type SearchHit,
} from "@/lib/ipc";

type Mode = "ask" | "search";

// One question and its answer. Follow-ups add turns to the same chat.
interface Turn {
  question: string;
  text: string;
  // What the answer is doing while no text streams (searching, reading).
  status: string | null;
  citations: Citation[];
  streaming: boolean;
  error: string | null;
  // Set when the answer waits for a tool approval, which only the main window can give.
  approval: { tool: string | null } | null;
}

// Cleared on sign-out and server change (launcher.rs `reset`).
const HISTORY_KEY = "onyx.launcher.history";
const HISTORY_SIZE = 20;

function loadHistory(): string[] {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(HISTORY_KEY) ?? "[]");
    return Array.isArray(saved) ? saved.filter((q): q is string => typeof q === "string") : [];
  } catch {
    return [];
  }
}

// History is optional: a full or unavailable store never blocks a question.
function remember(question: string) {
  const history = loadHistory().filter((q) => q !== question);
  history.push(question);
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(-HISTORY_SIZE)));
  } catch {
    // Not saved; the question still runs.
  }
}

function Launcher() {
  const inputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<Mode>("ask");
  const [query, setQuery] = useState("");
  // The panel keeps its chat, results and query while hidden; ⌘N starts over.
  const [turns, setTurns] = useState<Turn[]>([]);
  const [chatSessionId, setChatSessionId] = useState<string | null>(null);
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  // Each ask or search gets an id; updates from a replaced request are ignored.
  const askId = useRef(0);
  const searchId = useRef(0);
  // Position in the question history while ↑/↓ browse it; null otherwise.
  const historyAt = useRef<number | null>(null);

  useEffect(() => {
    // Back from hiding: typing replaces the last query, ↓ reaches the answer.
    function focus() {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
    focus();
    window.addEventListener("focus", focus);
    return () => window.removeEventListener("focus", focus);
  }, []);

  useEffect(() => {
    resultsRef.current?.scrollTo({ top: resultsRef.current.scrollHeight });
  }, [turns.length]);

  // Easter egg: five quick clicks on the logo bring Aonyx onto the screen.
  const logoClicks = useRef<number[]>([]);
  function onLogoClick() {
    const now = Date.now();
    logoClicks.current = [...logoClicks.current.filter((t) => now - t < 1500), now];
    if (logoClicks.current.length >= 5) {
      logoClicks.current = [];
      void invoke("toggle_aonyx");
    }
  }

  function newChat() {
    askId.current += 1;
    searchId.current += 1;
    setTurns([]);
    setChatSessionId(null);
    setQuery("");
    setHits(null);
    setSearching(false);
    setSearchError(null);
    inputRef.current?.focus();
  }

  function updateLast(change: (turn: Turn) => Turn) {
    setTurns((prev) => {
      const last = prev.at(-1);
      return last ? [...prev.slice(0, -1), change(last)] : prev;
    });
  }

  async function runAsk(question: string) {
    const id = ++askId.current;
    const last = turns.at(-1);
    // A follow-up continues the chat once its last answer is complete.
    const followUp = chatSessionId !== null && last !== undefined && !last.streaming && !last.error;
    const turn: Turn = {
      question,
      text: "",
      status: null,
      citations: [],
      streaming: true,
      error: null,
      approval: null,
    };
    setTurns((prev) => (followUp ? [...prev, turn] : [turn]));
    if (!followUp) setChatSessionId(null);
    try {
      await ask(question, followUp ? chatSessionId : null, (event) => {
        if (id !== askId.current) return;
        if (event.kind === "session") {
          setChatSessionId(event.chatSessionId);
          return;
        }
        updateLast((t) => {
          switch (event.kind) {
            case "delta":
              // Answer text replaces the progress line; a later tool step sets it again.
              return { ...t, text: t.text + event.text, status: event.text ? null : t.status };
            case "status":
              return { ...t, status: event.text };
            case "restart":
              // The earlier text was narration ("Retrying with a simpler query.").
              return {
                ...t,
                status: event.text ? null : t.text.trim() || t.status,
                text: event.text,
              };
            case "citations":
              return { ...t, citations: event.docs };
            case "needsApproval":
              return { ...t, approval: { tool: event.tool } };
            case "done":
              return { ...t, streaming: false, status: null };
            case "error":
              return { ...t, streaming: false, status: null, error: event.message };
          }
        });
      });
    } catch (e) {
      if (id !== askId.current) return;
      updateLast((t) => ({ ...t, streaming: false, status: null, error: errorMessage(e) }));
    }
  }

  async function runSearch(text: string) {
    const id = ++searchId.current;
    setSearching(true);
    setSearchError(null);
    try {
      const results = await search(text);
      if (id !== searchId.current) return;
      setHits(results);
    } catch (e) {
      if (id !== searchId.current) return;
      setSearchError(errorMessage(e));
      setHits(null);
    } finally {
      if (id === searchId.current) setSearching(false);
    }
  }

  // Answer links, citation buttons, and search result rows (role="button").
  function results(): HTMLElement[] {
    return Array.from(
      resultsRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not(:disabled), [role="button"]:not([aria-disabled="true"])'
      ) ?? []
    );
  }

  // An IME composition (Japanese, Chinese, Korean) uses Enter and Esc itself.
  // WebKit can send the confirming Enter after compositionend, with keyCode 229.
  function composing(event: KeyboardEvent<HTMLElement>): boolean {
    return event.nativeEvent.isComposing || event.keyCode === 229;
  }

  // Esc and ⌘↵ work wherever focus is inside the launcher. They are handled
  // while the event goes down to the focused control, so a focused result row
  // never also acts on them (its Enter opens the link).
  function onPanelKeyDownCapture(event: KeyboardEvent<HTMLDivElement>) {
    if (composing(event)) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      void hideLauncher();
    } else if (event.key === "Enter" && hasPrimaryModifier(event)) {
      event.preventDefault();
      event.stopPropagation();
      void openChatInMain(chatSessionId);
    } else if (event.key.toLowerCase() === "n" && hasPrimaryModifier(event)) {
      event.preventDefault();
      event.stopPropagation();
      newChat();
    }
  }

  function onPanelKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (composing(event)) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      // Arrow keys move between the input and the citations or results.
      const items = results();
      const at = items.indexOf(document.activeElement as HTMLElement);
      const onInput = document.activeElement === inputRef.current;
      if (!onInput && at < 0) return;
      event.preventDefault();
      const next = event.key === "ArrowDown" ? (onInput ? 0 : at + 1) : at - 1;
      if (next < 0) inputRef.current?.focus();
      else items[Math.min(next, items.length - 1)]?.focus();
    }
  }

  const awaitingApproval = turns.at(-1)?.approval != null;

  // ↑ in an empty input steps back through recent questions; ↓ steps forward.
  function browseHistory(event: KeyboardEvent<HTMLInputElement>): boolean {
    const browsing = historyAt.current !== null;
    if (event.key === "ArrowUp" && (query === "" || browsing)) {
      const history = loadHistory();
      const at = (historyAt.current ?? history.length) - 1;
      if (at < 0) return true;
      historyAt.current = at;
      setQuery(history[at] ?? "");
      return true;
    }
    if (event.key === "ArrowDown" && browsing) {
      const history = loadHistory();
      const at = (historyAt.current ?? 0) + 1;
      historyAt.current = at < history.length ? at : null;
      setQuery(at < history.length ? (history[at] ?? "") : "");
      return true;
    }
    return false;
  }

  function onInputKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (composing(event)) return;
    if (browseHistory(event)) {
      event.preventDefault();
      event.stopPropagation();
    } else if (event.key === "Tab") {
      event.preventDefault();
      setMode((m) => (m === "ask" ? "search" : "ask"));
    } else if (event.key === "Enter" && !hasPrimaryModifier(event) && query.trim() !== "") {
      event.preventDefault();
      // The server takes no new message while an answer waits for approval:
      // keep the draft; ⌘↵ approves in the window, ⌘N starts a new chat.
      if (mode === "ask" && awaitingApproval) return;
      const text = query.trim();
      remember(text);
      historyAt.current = null;
      if (mode === "ask") {
        // The question moves into the thread, like a chat input.
        setQuery("");
        void runAsk(text);
      } else void runSearch(text);
    }
  }

  return (
    <div
      className="h-full overflow-hidden rounded-16 border border-border-02 bg-background-neutral-00"
      onKeyDownCapture={onPanelKeyDownCapture}
      onKeyDown={onPanelKeyDown}
    >
      <Section gap={0} justifyContent="start" alignItems="stretch">
        <div className="drag-region" data-tauri-drag-region>
          <Section flexDirection="row" gap={1} justifyContent="start" height="fit" padding={3}>
            <button
              type="button"
              tabIndex={-1}
              aria-label="Onyx"
              className="me-1 cursor-default"
              onClick={onLogoClick}
            >
              <img src="/onyx-logo.svg" alt="" className="h-4 w-4" />
            </button>
            <Button
              size="sm"
              prominence={mode === "ask" ? "secondary" : "tertiary"}
              aria-pressed={mode === "ask"}
              onClick={() => setMode("ask")}
            >
              Ask
            </Button>
            <Button
              size="sm"
              prominence={mode === "search" ? "secondary" : "tertiary"}
              aria-pressed={mode === "search"}
              onClick={() => setMode("search")}
            >
              Search
            </Button>
            <Section flexDirection="row" justifyContent="end" height="fit">
              <Text font="secondary-body" color="text-02">
                {`Tab switches · ${primaryShortcut("N")} new chat · ${primaryShortcut("Enter")} opens in window · Esc closes`}
              </Text>
            </Section>
          </Section>
        </div>
        <div className="px-3 pb-3">
          <InputTypeIn
            id="launcher-input"
            ref={inputRef}
            value={query}
            spellCheck={false}
            onChange={(e) => {
              historyAt.current = null;
              setQuery(e.target.value);
            }}
            onKeyDown={onInputKeyDown}
            placeholder={
              mode === "search"
                ? "Search your company's knowledge…"
                : awaitingApproval
                  ? `Approve with ${primaryShortcut("Enter")} in the Onyx window, or ${primaryShortcut("N")} for a new chat`
                  : turns.length > 0
                  ? "Ask a follow-up…"
                  : "Ask Onyx anything…"
            }
          />
        </div>
        <div
          ref={resultsRef}
          className="selectable flex-1 overflow-y-auto border-t border-border-01 p-4"
        >
          {mode === "ask" ? <ChatView turns={turns} /> : null}
          {mode === "search" ? (
            <SearchView hits={hits} searching={searching} error={searchError} />
          ) : null}
        </div>
      </Section>
    </div>
  );
}

// A local window cannot follow links itself; they open through the app, which
// opens web links and server paths only. Other links show as plain text.
const OPENABLE_LINK = /^(https?:|\/)/i;

const ANSWER_COMPONENTS: CompactMarkdownProps["components"] = {
  a: ({ children, href }) =>
    href && OPENABLE_LINK.test(href) ? (
      <a
        href={href}
        className="text-link hover:text-link-hover underline underline-offset-2"
        onClick={(event) => {
          event.preventDefault();
          void openExternal(href);
        }}
      >
        {children}
      </a>
    ) : (
      <>{children}</>
    ),
};

interface ChatViewProps {
  turns: Turn[];
}

function ChatView({ turns }: ChatViewProps) {
  if (turns.length === 0) {
    return (
      <Text font="main-ui-muted" color="text-02">
        Press Enter to ask. The answer streams here; ↑ shows recent questions.
      </Text>
    );
  }
  return (
    <Section gap={5} alignItems="stretch" justifyContent="start" height="fit">
      {turns.map((turn, i) => (
        <TurnView key={i} turn={turn} />
      ))}
    </Section>
  );
}

function TurnView({ turn }: { turn: Turn }) {
  return (
    <Section gap={2} alignItems="start" justifyContent="start" height="fit">
      <Text font="main-ui-action" color="text-05">
        {turn.question}
      </Text>
      {turn.streaming && !turn.text ? (
        <StatusLine text={turn.status ?? "Thinking…"} />
      ) : null}
      {turn.text ? (
        <CompactMarkdown components={ANSWER_COMPONENTS}>
          {turn.streaming ? `${turn.text}▍` : turn.text}
        </CompactMarkdown>
      ) : null}
      {turn.streaming && turn.text && turn.status ? <StatusLine text={turn.status} /> : null}
      {turn.error ? (
        <Text font="main-ui-body" color="text-04">
          {turn.error}
        </Text>
      ) : null}
      {turn.approval ? (
        <Text font="main-ui-body" color="text-03">
          {`Onyx needs your approval to use ${turn.approval.tool ?? "a tool"}. Press ${primaryShortcut("Enter")} to continue in the Onyx window.`}
        </Text>
      ) : null}
      {turn.citations.length > 0 ? (
        <Section flexDirection="row" gap={1} justifyContent="start" wrap height="fit">
          {turn.citations.map((citation, i) => (
            <Button
              key={`${citation.title}-${i}`}
              size="sm"
              prominence="secondary"
              disabled={!citation.link}
              onClick={() => citation.link && void openExternal(citation.link)}
            >
              {`[${citation.number}] ${citation.title}`}
            </Button>
          ))}
        </Section>
      ) : null}
    </Section>
  );
}

// Shown while an answer works without streaming text.
function StatusLine({ text }: { text: string }) {
  return (
    <div role="status" className="flex items-center gap-2">
      <span className="h-2 w-2 animate-pulse rounded-full bg-background-tint-inverted-03" />
      <Text font="secondary-body" color="text-03">
        {text}
      </Text>
    </div>
  );
}

interface SearchViewProps {
  hits: SearchHit[] | null;
  searching: boolean;
  error: string | null;
}

function SearchView({ hits, searching, error }: SearchViewProps) {
  if (error) {
    return (
      <Text font="main-ui-body" color="text-04">
        {error}
      </Text>
    );
  }
  if (searching) {
    return (
      <Text font="main-ui-muted" color="text-02">
        Searching…
      </Text>
    );
  }
  if (hits === null) {
    return (
      <Text font="main-ui-muted" color="text-02">
        Press Enter to search connected sources.
      </Text>
    );
  }
  if (hits.length === 0) {
    return (
      <Text font="main-ui-muted" color="text-02">
        No documents matched.
      </Text>
    );
  }
  return (
    <Section gap={1} alignItems="stretch" justifyContent="start" height="fit">
      {hits.map((hit) => (
        <LineItemButton
          key={hit.documentId}
          title={hit.title}
          description={`${hit.sourceType} · ${hit.blurb}`}
          onClick={() => hit.link && void openExternal(hit.link)}
        />
      ))}
    </Section>
  );
}

mount(<Launcher />, "launcher");
