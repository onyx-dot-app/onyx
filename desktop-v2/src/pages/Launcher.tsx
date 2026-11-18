import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Button, InputTypeIn, LineItemButton, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { mount } from "@/lib/mount";
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

interface AnswerState {
  text: string;
  citations: Citation[];
  chatSessionId: string | null;
  streaming: boolean;
  error: string | null;
  // Set when the answer waits for a tool approval, which only the main window can give.
  approval: { tool: string | null } | null;
}

const EMPTY_ANSWER: AnswerState = {
  text: "",
  citations: [],
  chatSessionId: null,
  streaming: false,
  error: null,
  approval: null,
};

function Launcher() {
  const inputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<Mode>("ask");
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState<AnswerState>(EMPTY_ANSWER);
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  // Each ask or search gets an id; updates from a replaced request are ignored.
  const askId = useRef(0);
  const searchId = useRef(0);

  useEffect(() => {
    function focus() {
      inputRef.current?.focus();
    }
    focus();
    window.addEventListener("focus", focus);
    return () => window.removeEventListener("focus", focus);
  }, []);

  async function runAsk(question: string) {
    const id = ++askId.current;
    setAnswer({ ...EMPTY_ANSWER, streaming: true });
    try {
      await ask(question, (event) => {
        if (id !== askId.current) return;
        setAnswer((prev) => {
          switch (event.kind) {
            case "session":
              return { ...prev, chatSessionId: event.chatSessionId };
            case "delta":
              return { ...prev, text: prev.text + event.text };
            case "citations":
              return { ...prev, citations: event.docs };
            case "needsApproval":
              return { ...prev, approval: { tool: event.tool } };
            case "done":
              return { ...prev, streaming: false };
            case "error":
              return { ...prev, streaming: false, error: event.message };
          }
        });
      });
    } catch (e) {
      if (id !== askId.current) return;
      setAnswer((prev) => ({ ...prev, streaming: false, error: errorMessage(e) }));
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

  // Citations are buttons; search results are rows with role="button".
  function results(): HTMLElement[] {
    return Array.from(
      resultsRef.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), [role="button"]:not([aria-disabled="true"])'
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
    } else if (event.key === "Enter" && event.metaKey) {
      event.preventDefault();
      event.stopPropagation();
      void openChatInMain(answer.chatSessionId);
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

  function onInputKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (composing(event)) return;
    if (event.key === "Tab") {
      event.preventDefault();
      setMode((m) => (m === "ask" ? "search" : "ask"));
    } else if (event.key === "Enter" && !event.metaKey && query.trim() !== "") {
      event.preventDefault();
      if (mode === "ask") void runAsk(query.trim());
      else void runSearch(query.trim());
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
            <img src="/onyx-logo.svg" alt="" className="me-1 h-4 w-4" />
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
                Tab switches · ↓ results · ⌘↵ opens in window · Esc closes
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
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onInputKeyDown}
            placeholder={
              mode === "ask" ? "Ask Onyx anything…" : "Search your company's knowledge…"
            }
          />
        </div>
        <div
          ref={resultsRef}
          className="selectable flex-1 overflow-y-auto border-t border-border-01 p-4"
        >
          {mode === "ask" ? <AnswerView answer={answer} /> : null}
          {mode === "search" ? (
            <SearchView hits={hits} searching={searching} error={searchError} />
          ) : null}
        </div>
      </Section>
    </div>
  );
}

interface AnswerViewProps {
  answer: AnswerState;
}

function AnswerView({ answer }: AnswerViewProps) {
  if (answer.error) {
    return (
      <Text font="main-ui-body" color="text-04">
        {answer.error}
      </Text>
    );
  }
  if (!answer.text && !answer.streaming && !answer.approval) {
    return (
      <Text font="main-ui-muted" color="text-02">
        Press Enter to ask. The answer streams here.
      </Text>
    );
  }
  return (
    <Section gap={3} alignItems="start" justifyContent="start" height="fit">
      {answer.text || answer.streaming ? (
        <Text font="main-content-body" color="text-04">
          {answer.streaming ? `${answer.text}▍` : answer.text}
        </Text>
      ) : null}
      {answer.approval ? (
        <Text font="main-ui-body" color="text-03">
          {`Onyx needs your approval to use ${answer.approval.tool ?? "a tool"}. Press ⌘↵ to continue in the Onyx window.`}
        </Text>
      ) : null}
      {answer.citations.length > 0 ? (
        <Section flexDirection="row" gap={1} justifyContent="start" wrap height="fit">
          {answer.citations.map((citation, i) => (
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
