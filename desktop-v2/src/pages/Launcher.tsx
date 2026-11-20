import {
  useEffect,
  useRef,
  useState,
  type ClipboardEvent,
  type DragEvent,
  type KeyboardEvent,
} from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import {
  Button,
  CompactMarkdown,
  type CompactMarkdownProps,
  InputTypeIn,
  LineItemButton,
  Tag,
  Text,
} from "@opal/components";
import { SvgBubbleText, SvgImage, SvgPaperclip } from "@opal/icons";
import { Section } from "@opal/layouts";
import { mount } from "@/lib/mount";
import { hasPrimaryModifier, primaryShortcut } from "@/lib/platform";
import {
  ask,
  cancelUpload,
  DEFAULT_AGENT_ID,
  deleteUserFile,
  discardAnswer,
  errorMessage,
  getPrefs,
  getUploadLimit,
  hideLauncher,
  listAgents,
  openChatInMain,
  openExternal,
  search,
  setLauncherAgent,
  uploadFile,
  type Agent,
  type AttachedFile,
  type Citation,
  type SearchHit,
} from "@/lib/ipc";

type Mode = "ask" | "search";

// One question and its answer. Follow-ups add turns to the same chat.
interface Turn {
  question: string;
  // Names of the files sent with the question.
  files: string[];
  text: string;
  // What the answer is doing while no text streams (searching, reading).
  status: string | null;
  citations: Citation[];
  streaming: boolean;
  error: string | null;
  // Set when the answer waits for a tool approval, which only the main window can give.
  approval: { tool: string | null } | null;
}

// A file for the next question: uploading while `file` and `error` are null.
interface Attachment {
  key: number;
  name: string;
  isImage: boolean;
  file: AttachedFile | null;
  error: string | null;
}

// Cleared on sign-out and server change (launcher.rs `reset`).
const HISTORY_KEY = "onyx.launcher.history";
const HISTORY_SIZE = 20;
const MAX_ATTACHMENTS = 10;
// The app's own limit (api.rs MAX_UPLOAD_BYTES): a file is in memory while it
// uploads. The server's limit can be lower.
const MAX_FILE_BYTES = 250 * 1024 * 1024;
// Uploads that read files into memory at one time; the others wait.
const PARALLEL_UPLOADS = 2;
const AGENT_REFRESH_MS = 60_000;
// How long a question waits for the first agent list before it goes as is.
const AGENT_WAIT_MS = 3_000;

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

const EXTENSIONS: Record<string, string> = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/gif": "gif",
  "image/webp": "webp",
  "text/plain": "txt",
  "application/pdf": "pdf",
};

// The server finds a file's kind from its extension; a pasted screenshot can
// arrive without a name.
function attachmentName(file: File): string {
  if (file.name.includes(".")) return file.name;
  const extension = EXTENSIONS[file.type];
  const base = file.name || (file.type.startsWith("image/") ? "pasted-image" : "pasted-file");
  return extension ? `${base}.${extension}` : base;
}

// Copies from a key press. execCommand runs inside the key event, which
// every web view allows; the async clipboard API is the fallback. Resolves
// true once the text is on the clipboard.
async function copyText(text: string): Promise<boolean> {
  const active = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch {
    copied = false;
  }
  area.remove();
  active?.focus();
  if (copied) return true;
  if (!navigator.clipboard) return false;
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function megabytes(bytes: number): number {
  return Math.floor(bytes / (1024 * 1024));
}

// "unchanged": the list was fresh, or a newer refresh replaced this one.
type AgentRefresh = Agent[] | "failed" | "unchanged";

interface UploadJob {
  key: number;
  file: File;
  name: string;
}

function agentMatches(agents: Agent[], filter: string): Agent[] {
  const needle = filter.trim().toLowerCase();
  const matching = agents.filter((a) => a.name.toLowerCase().includes(needle));
  // Names that start with the filter come first.
  return [
    ...matching.filter((a) => a.name.toLowerCase().startsWith(needle)),
    ...matching.filter((a) => !a.name.toLowerCase().startsWith(needle)),
  ];
}

function sourceLabel(source: string): string {
  return source
    .split("_")
    .map((word) => (word ? word[0]!.toUpperCase() + word.slice(1) : word))
    .join(" ");
}

function Launcher() {
  const inputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<Mode>("ask");

  // A notification click is for the answer, even if Search was open.
  useEffect(() => {
    const unlisten = listen("launcher-show-answer", () => setMode("ask"));
    return () => {
      void unlisten.then((stop) => stop());
    };
  }, []);
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

  // Agents. null is the server's default agent.
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentId, setAgentId] = useState<number | null>(null);
  // "Always Start with an Agent": the default agent cannot start a chat.
  const [defaultDisabled, setDefaultDisabled] = useState(false);
  const agentsRequest = useRef(0);
  // The agent of the chat on screen; a different agent starts a new chat.
  const [chatAgentId, setChatAgentId] = useState<number | null>(null);
  const agentsLoadedAt = useRef<number | null>(null);
  // The first agent list is loading; a question waits for the saved agent.
  const [agentsPending, setAgentsPending] = useState(false);
  // The question the user submitted while the first agent list loaded.
  const [askQueued, setAskQueued] = useState<string | null>(null);
  const [agentWaitOver, setAgentWaitOver] = useState(false);
  const [pickerIndex, setPickerIndex] = useState(0);
  const [pickerDismissed, setPickerDismissed] = useState(false);
  // The draft that ⌘K set aside to show the picker; null when "@" opened it.
  const pickerDraft = useRef<string | null>(null);
  // Each ⌘K gets an id; ⌘N drops one that still waits for the agent list.
  const pickerRequest = useRef(0);

  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const attachmentKey = useRef(0);
  const uploadQueue = useRef<UploadJob[]>([]);
  const activeUploads = useRef(new Set<number>());
  // Keys of the chips on screen. A file whose chip is gone is deleted, unless
  // it was sent with a question.
  const liveKeys = useRef(new Set<number>());
  // Read once each time the launcher shows.
  const uploadLimit = useRef<Promise<number> | null>(null);
  const [dragging, setDragging] = useState(false);

  // Search source filter; the sources come from the last unfiltered results.
  const [lastSearch, setLastSearch] = useState("");
  const [sources, setSources] = useState<string[]>([]);
  const [sourceFilter, setSourceFilter] = useState<string | null>(null);

  // A short confirmation ("Copied the answer") in the hint row.
  const [notice, setNotice] = useState<string | null>(null);
  const noticeTimer = useRef<number | undefined>(undefined);
  const serverUrl = useRef<string | null>(null);

  function flash(text: string) {
    setNotice(text);
    window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(null), 2500);
  }

  // Failures keep the list the launcher has; servers without the list have no agents.
  async function refreshAgents(force = false): Promise<AgentRefresh> {
    const loadedAt = agentsLoadedAt.current;
    if (!force && loadedAt !== null && Date.now() - loadedAt < AGENT_REFRESH_MS) {
      return "unchanged";
    }
    const request = ++agentsRequest.current;
    if (loadedAt === null) setAgentsPending(true);
    try {
      const result = await listAgents();
      if (request !== agentsRequest.current) return "unchanged";
      setAgents(result.agents);
      setDefaultDisabled(result.defaultAgentDisabled);
      const usable = (id: number | null) =>
        id === null ? !result.defaultAgentDisabled : result.agents.some((a) => a.id === id);
      if (loadedAt === null) setAgentId(result.selected);
      else setAgentId((id) => (usable(id) ? id : result.selected));
      agentsLoadedAt.current = Date.now();
      return result.agents;
    } catch {
      // The default agent still answers.
      return request === agentsRequest.current ? "failed" : "unchanged";
    } finally {
      if (request === agentsRequest.current) setAgentsPending(false);
    }
  }

  useEffect(() => {
    // Back from hiding: typing replaces the last query, ↓ reaches the answer.
    function focus() {
      inputRef.current?.focus();
      inputRef.current?.select();
      void refreshAgents();
      uploadLimit.current = null;
      // The server can change while the launcher is hidden (onboarding, sign-in).
      void getPrefs().then(
        (prefs) => (serverUrl.current = prefs.serverUrl),
        () => undefined
      );
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
    void discardAnswer();
    askId.current += 1;
    searchId.current += 1;
    setAskQueued(null);
    setTurns([]);
    setChatSessionId(null);
    setQuery("");
    setHits(null);
    setSearching(false);
    setSearchError(null);
    setSources([]);
    setSourceFilter(null);
    discardAttachments(attachments);
    setAttachments([]);
    pickerRequest.current += 1;
    pickerDraft.current = null;
    setPickerDismissed(false);
    setPickerIndex(0);
    inputRef.current?.focus();
  }

  function updateLast(change: (turn: Turn) => Turn) {
    setTurns((prev) => {
      const last = prev.at(-1);
      return last ? [...prev.slice(0, -1), change(last)] : prev;
    });
  }

  async function runAsk(question: string, sent: Attachment[]) {
    const id = ++askId.current;
    const files = sent.flatMap((a) => (a.file ? [a.file] : []));
    // Set once the question may have reached the server.
    let sending = false;
    const notSent = () => {
      if (!sending) returnFiles(id, sent);
      sending = true;
    };
    const last = turns.at(-1);
    // A follow-up continues the chat once its last answer is complete, with the same agent.
    const followUp =
      chatSessionId !== null &&
      last !== undefined &&
      !last.streaming &&
      !last.error &&
      chatAgentId === agentId;
    const turn: Turn = {
      question,
      files: files.map((f) => f.name),
      text: "",
      status: null,
      citations: [],
      streaming: true,
      error: null,
      approval: null,
    };
    setTurns((prev) => (followUp ? [...prev, turn] : [turn]));
    if (!followUp) {
      setChatSessionId(null);
      setChatAgentId(agentId);
    }
    try {
      await ask(
        question,
        { chatSessionId: followUp ? chatSessionId : null, agentId, files },
        (event) => {
          if (event.kind === "session") sending = true;
          // A refused question (for example a usage limit) gets its files back.
          else if (event.kind === "notSent") sending = false;
          else if (event.kind === "error") notSent();
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
              case "notSent":
                return t;
              case "error":
                return { ...t, streaming: false, status: null, error: event.message };
            }
          });
        }
      );
    } catch (e) {
      notSent();
      if (id !== askId.current) return;
      updateLast((t) => ({ ...t, streaming: false, status: null, error: errorMessage(e) }));
    }
  }

  // The files of a question that was not sent go back to the input. After ⌘N
  // or a newer question, nothing will send them, so they are deleted.
  function returnFiles(id: number, sent: Attachment[]) {
    if (sent.length === 0) return;
    if (id !== askId.current) {
      discardAttachments(sent);
      return;
    }
    for (const a of sent) liveKeys.current.add(a.key);
    setAttachments((prev) => [...sent, ...prev]);
  }

  async function runSearch(text: string, filter: string | null) {
    const id = ++searchId.current;
    setSearching(true);
    setSearchError(null);
    // A new query's filters come from its own results.
    if (text !== lastSearch) setSources([]);
    setLastSearch(text);
    setSourceFilter(filter);
    try {
      const results = await search(text, filter ? [filter] : []);
      if (id !== searchId.current) return;
      setHits(results);
      if (!filter) setSources([...new Set(results.map((h) => h.sourceType).filter(Boolean))]);
    } catch (e) {
      if (id !== searchId.current) return;
      setSearchError(errorMessage(e));
      setHits(null);
    } finally {
      if (id === searchId.current) setSearching(false);
    }
  }

  function toggleSource(source: string) {
    if (!lastSearch) return;
    void runSearch(lastSearch, sourceFilter === source ? null : source);
  }

  // ── Agents ──

  const agent = agentId === null ? null : (agents.find((a) => a.id === agentId) ?? null);
  // Stays open when no agent matches, so Enter does not send the filter.
  const pickerOpen =
    mode === "ask" && query.startsWith("@") && !pickerDismissed && agents.length > 0;
  const pickerMatches = pickerOpen ? agentMatches(agents, query.slice(1)).slice(0, 50) : [];
  const highlighted = pickerMatches[Math.min(pickerIndex, pickerMatches.length - 1)];
  const highlightedId = highlighted?.id ?? null;

  // The input keeps focus, so the list does not scroll to the highlighted row itself.
  useEffect(() => {
    if (highlightedId === null) return;
    resultsRef.current
      ?.querySelector(`[data-agent-id="${highlightedId}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [highlightedId]);

  function chooseAgent(next: Agent | null) {
    const id = next === null || next.id === DEFAULT_AGENT_ID ? null : next.id;
    if (id === null && defaultDisabled) return;
    setAgentId(id);
    // Remembering is optional; the choice still applies now.
    void setLauncherAgent(id).catch(() => undefined);
  }

  // ⌘K's set-aside draft comes back; a typed "@…" is kept as text when cancelled.
  function closePicker(cancelled: boolean) {
    const draft = pickerDraft.current;
    pickerDraft.current = null;
    if (draft !== null) setQuery(draft);
    else if (cancelled) setPickerDismissed(true);
    else setQuery("");
    setPickerIndex(0);
    inputRef.current?.focus();
  }

  function pickAgent(next: Agent) {
    chooseAgent(next);
    closePicker(false);
  }

  async function openPicker() {
    const request = ++pickerRequest.current;
    if (mode !== "ask") setMode("ask");
    if (agents.length === 0) {
      // An earlier load can have failed; try again before saying there are none.
      const result = await refreshAgents(true);
      if (request !== pickerRequest.current) return;
      if (result === "failed") {
        flash("Could not load the agents. Try again.");
        return;
      }
      if (result === "unchanged") return;
      if (result.length === 0) {
        flash("This server has no other agents to choose.");
        return;
      }
    } else {
      // The list may be up to a minute old; an agent added meanwhile shows up.
      void refreshAgents(true);
    }
    const draft = inputRef.current?.value ?? query;
    if (!draft.startsWith("@")) pickerDraft.current = draft;
    setQuery("@");
    setPickerDismissed(false);
    setPickerIndex(0);
    inputRef.current?.focus();
  }

  // ── Attachments ──

  const uploading = attachments.some((a) => a.file === null && a.error === null);
  const failed = attachments.some((a) => a.error !== null);

  function settle(key: number, change: Partial<Attachment>) {
    setAttachments((prev) => prev.map((a) => (a.key === key ? { ...a, ...change } : a)));
  }

  function serverUploadLimit(): Promise<number> {
    uploadLimit.current ??= getUploadLimit().catch(() => MAX_FILE_BYTES);
    return uploadLimit.current;
  }

  // Starts queued uploads while fewer than PARALLEL_UPLOADS run.
  function pumpUploads() {
    while (activeUploads.current.size < PARALLEL_UPLOADS) {
      const job = uploadQueue.current.shift();
      if (!job) return;
      activeUploads.current.add(job.key);
      void runUpload(job).finally(() => {
        activeUploads.current.delete(job.key);
        pumpUploads();
      });
    }
  }

  async function runUpload({ key, file, name }: UploadJob) {
    // Checked before the file is read into memory.
    const limit = await serverUploadLimit();
    if (!liveKeys.current.has(key)) return;
    if (file.size > limit) {
      settle(key, {
        error: `${name} is larger than ${megabytes(limit)} MB, the largest file you can attach.`,
      });
      return;
    }
    try {
      const live = () => liveKeys.current.has(key);
      const uploaded = await uploadFile(file, name, key, live);
      if (liveKeys.current.has(key)) settle(key, { file: uploaded });
      // Removed while the server finished it.
      else {
        const isImage = file.type.startsWith("image/");
        deleteFile({ key, name, isImage, file: uploaded, error: null });
      }
    } catch (e) {
      if (liveKeys.current.has(key)) settle(key, { error: errorMessage(e) });
    }
  }

  function addFiles(files: File[]) {
    if (files.length === 0) return;
    setMode("ask");
    const room = MAX_ATTACHMENTS - attachments.length;
    if (room <= 0) {
      flash(`You can attach up to ${MAX_ATTACHMENTS} files.`);
      return;
    }
    if (files.length > room) flash(`You can attach up to ${MAX_ATTACHMENTS} files.`);
    for (const file of files.slice(0, room)) {
      const key = ++attachmentKey.current;
      const name = attachmentName(file);
      const error =
        file.size > MAX_FILE_BYTES
          ? `${name} is larger than ${megabytes(MAX_FILE_BYTES)} MB, the largest file you can attach.`
          : file.size === 0
            ? `${name} is empty or is a folder.`
            : null;
      const isImage = file.type.startsWith("image/");
      liveKeys.current.add(key);
      setAttachments((prev) => [...prev, { key, name, isImage, file: null, error }]);
      if (!error) uploadQueue.current.push({ key, file, name });
    }
    pumpUploads();
  }

  // A file the server did not delete comes back as a failed chip; removing it
  // again tries again.
  function deleteFile(a: Attachment) {
    if (!a.file) return;
    void deleteUserFile(a.file.userFileId).catch(() => {
      liveKeys.current.add(a.key);
      const error = `Could not remove ${a.name} from your files. Remove it again to try again.`;
      setAttachments((prev) =>
        prev.some((p) => p.key === a.key) ? prev : [...prev, { ...a, error }]
      );
    });
  }

  // Stops the uploads of chips that go away and deletes their files.
  function discardAttachments(list: Attachment[]) {
    for (const a of list) {
      liveKeys.current.delete(a.key);
      if (a.file) {
        deleteFile(a);
      } else if (activeUploads.current.has(a.key)) {
        void cancelUpload(a.key).catch(() => undefined);
      } else {
        uploadQueue.current = uploadQueue.current.filter((job) => job.key !== a.key);
      }
    }
  }

  function removeAttachment(key: number) {
    discardAttachments(attachments.filter((a) => a.key === key));
    setAttachments((prev) => prev.filter((a) => a.key !== key));
  }

  function onPaste(event: ClipboardEvent<HTMLDivElement>) {
    const files = Array.from(event.clipboardData.files);
    if (files.length === 0) return;
    event.preventDefault();
    addFiles(files);
  }

  function hasFiles(event: DragEvent<HTMLDivElement>): boolean {
    return Array.from(event.dataTransfer.types).includes("Files");
  }

  function onDragOver(event: DragEvent<HTMLDivElement>) {
    if (!hasFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setDragging(true);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    setDragging(false);
    if (!hasFiles(event)) return;
    event.preventDefault();
    addFiles(Array.from(event.dataTransfer.files));
    inputRef.current?.focus();
  }

  // ── Result actions ──

  const lastTurn = turns.at(-1);
  const answer = lastTurn && !lastTurn.streaming && lastTurn.text ? lastTurn.text : null;

  // The source for ⌘<n>: the answer's citation [n], or the nth search result.
  function sourceLink(n: number): string | null {
    if (mode === "ask") {
      return lastTurn?.citations.find((c) => c.number === n)?.link ?? null;
    }
    // The results on screen are from the search before.
    if (searching) return null;
    return hits?.[n - 1]?.link ?? null;
  }

  // Search results and citations can link to a server path.
  function absoluteLink(link: string): string {
    if (!serverUrl.current) return link;
    try {
      return new URL(link, serverUrl.current).toString();
    } catch {
      return link;
    }
  }

  function hasTextSelection(): boolean {
    const input = inputRef.current;
    if (input && document.activeElement === input && input.selectionStart !== input.selectionEnd) {
      return true;
    }
    return (window.getSelection()?.toString() ?? "") !== "";
  }

  // ⌘C copies the focused source's link, or the answer, when no text is
  // selected; ⌘⇧C always copies the answer.
  function onCopyKey(event: KeyboardEvent<HTMLDivElement>): boolean {
    if (!event.shiftKey) {
      if (hasTextSelection()) return false;
      const link = (document.activeElement as HTMLElement | null)?.dataset.link;
      if (link) {
        copyAndFlash(absoluteLink(link), "link");
        return true;
      }
    }
    if (mode !== "ask" || !answer) return false;
    copyAndFlash(answer, "answer");
    return true;
  }

  function copyAndFlash(text: string, what: "answer" | "link") {
    void copyText(text).then((copied) =>
      flash(copied ? `Copied the ${what}` : `Could not copy the ${what}`)
    );
  }

  function onSourceKey(event: KeyboardEvent<HTMLDivElement>): boolean {
    const digit = /^Digit([1-9])$/.exec(event.code)?.[1];
    if (!digit) return false;
    const link = sourceLink(Number(digit));
    if (!link) return true;
    if (event.shiftKey) {
      copyAndFlash(absoluteLink(link), "link");
    } else {
      void openExternal(link);
    }
    return true;
  }

  // An IME composition (Japanese, Chinese, Korean) uses Enter and Esc itself.
  // WebKit can send the confirming Enter after compositionend, with keyCode 229.
  function composing(event: KeyboardEvent<HTMLElement>): boolean {
    return event.nativeEvent.isComposing || event.keyCode === 229;
  }

  // Esc and ⌘ shortcuts work wherever focus is inside the launcher. They are
  // handled while the event goes down to the focused control, so a focused
  // result row never also acts on them (its Enter opens the link).
  function onPanelKeyDownCapture(event: KeyboardEvent<HTMLDivElement>) {
    if (composing(event)) return;
    const key = event.key.toLowerCase();
    let handled = true;
    if (event.key === "Escape") {
      if (pickerOpen) closePicker(true);
      else void hideLauncher();
    } else if (!hasPrimaryModifier(event)) {
      handled = false;
    } else if (event.key === "Enter") {
      void openChatInMain(chatSessionId);
    } else if (key === "n" && !event.shiftKey) {
      newChat();
    } else if (key === "k") {
      if (pickerOpen) closePicker(true);
      else void openPicker();
    } else if (key === "c") {
      handled = onCopyKey(event);
    } else {
      handled = onSourceKey(event);
    }
    if (handled) {
      event.preventDefault();
      event.stopPropagation();
    }
  }

  // Answer links, citation buttons, source filters and search result rows (role="button").
  function results(): HTMLElement[] {
    return Array.from(
      resultsRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not(:disabled), [role="button"]:not([aria-disabled="true"])'
      ) ?? []
    );
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

  // The server takes no new message in a chat that waits for approval. A
  // question to another agent starts a new chat, so it can still go.
  const awaitingApproval = turns.at(-1)?.approval != null && chatAgentId === agentId;

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

  // ↑/↓ move through the agent list, Enter or Tab picks.
  function pickerKey(event: KeyboardEvent<HTMLInputElement>): boolean {
    if (!pickerOpen) return false;
    const count = pickerMatches.length;
    const at = Math.min(pickerIndex, count - 1);
    if (event.key === "ArrowDown") {
      if (count > 0) setPickerIndex((at + 1) % count);
    } else if (event.key === "ArrowUp") {
      if (count > 0) setPickerIndex((at - 1 + count) % count);
    } else if (event.key === "Enter" || event.key === "Tab") {
      if (highlighted) pickAgent(highlighted);
    } else return false;
    return true;
  }

  function submitAsk(text: string) {
    // The server takes no new message while an answer waits for approval:
    // keep the draft; ⌘↵ approves in the window, ⌘N starts a new chat.
    if (awaitingApproval) return;
    // Without the saved agent, this question and the next would go to different chats.
    if (agentsPending && !agentWaitOver) {
      setAskQueued(text);
      return;
    }
    if (agentId === null && defaultDisabled) {
      flash(
        agents.length === 0
          ? "This server needs an agent for new chats, and you have no agent to use."
          : `Choose an agent first: type @ or press ${primaryShortcut("K")}.`
      );
      return;
    }
    if (uploading) {
      flash("Wait until the files finish uploading.");
      return;
    }
    if (failed) {
      flash("Remove the files that could not be attached.");
      return;
    }
    // Files returned from a refused question can join newer ones.
    if (attachments.length > MAX_ATTACHMENTS) {
      flash(`Remove files to send at most ${MAX_ATTACHMENTS}.`);
      return;
    }
    const sent = attachments.filter((a) => a.file !== null);
    // Sent files stay on the server; their chips leave without a delete.
    for (const a of attachments) liveKeys.current.delete(a.key);
    remember(text);
    historyAt.current = null;
    // The question and its files move into the thread, like a chat input.
    setQuery("");
    setAttachments([]);
    void runAsk(text, sent);
  }

  // A queued question goes once the first agent list settles, or after AGENT_WAIT_MS.
  useEffect(() => {
    if (askQueued === null) return;
    if (agentsPending && !agentWaitOver) {
      const timer = window.setTimeout(() => setAgentWaitOver(true), AGENT_WAIT_MS);
      return () => window.clearTimeout(timer);
    }
    setAskQueued(null);
    // A draft edited after Enter waits for another Enter.
    if (mode === "ask" && query.trim() === askQueued) submitAsk(askQueued);
    setAgentWaitOver(false);
  }, [askQueued, agentsPending, agentWaitOver]);

  function onInputKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (composing(event)) return;
    const lastAttachment = attachments.at(-1);
    if (pickerKey(event) || browseHistory(event)) {
      event.preventDefault();
      event.stopPropagation();
    } else if (event.key === "Backspace" && query === "" && mode === "ask" && lastAttachment) {
      // Backspace in an empty input removes the last chip: the files, then the agent.
      event.preventDefault();
      removeAttachment(lastAttachment.key);
    } else if (
      event.key === "Backspace" &&
      query === "" &&
      mode === "ask" &&
      agentId !== null &&
      !defaultDisabled
    ) {
      // Backspace in an empty input removes the agent chip.
      event.preventDefault();
      chooseAgent(null);
    } else if (event.key === "Tab") {
      event.preventDefault();
      setMode((m) => (m === "ask" ? "search" : "ask"));
    } else if (event.key === "Enter" && !hasPrimaryModifier(event) && query.trim() !== "") {
      event.preventDefault();
      const text = query.trim();
      if (mode === "ask") submitAsk(text);
      else {
        remember(text);
        historyAt.current = null;
        void runSearch(text, null);
      }
    }
  }

  const followsUp = turns.length > 0 && chatAgentId === agentId;
  const placeholder =
    mode === "search"
      ? "Search your company's knowledge…"
      : awaitingApproval
        ? `Approve with ${primaryShortcut("Enter")} in the Onyx window, or ${primaryShortcut("N")} for a new chat`
        : followsUp
          ? "Ask a follow-up…"
          : agent
            ? `Ask ${agent.name}…`
            : "Ask Onyx anything…";

  const showChips = mode === "ask" && (agent !== null || attachments.length > 0);
  const attachmentErrors = attachments.flatMap((a) => (a.error ? [a.error] : []));

  return (
    <div
      className={`h-full overflow-hidden rounded-16 border bg-background-neutral-00 ${
        dragging ? "border-border-05" : "border-border-02"
      }`}
      onKeyDownCapture={onPanelKeyDownCapture}
      onKeyDown={onPanelKeyDown}
      onPaste={onPaste}
      onDragOver={onDragOver}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={onDrop}
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
              const next = e.target.value;
              setPickerIndex(0);
              if (!next.startsWith("@")) {
                setPickerDismissed(false);
                // Deleting ⌘K's "@" closes the picker and brings the draft back.
                if (pickerDraft.current !== null) {
                  closePicker(true);
                  return;
                }
              } else if (!query.startsWith("@") && mode === "ask") {
                void refreshAgents(true);
              }
              setQuery(next);
            }}
            onKeyDown={onInputKeyDown}
            placeholder={placeholder}
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={pickerOpen}
            aria-controls={pickerMatches.length > 0 ? AGENT_LIST_ID : undefined}
            aria-activedescendant={highlighted ? agentOptionId(highlighted.id) : undefined}
          />
          {showChips ? (
            <div className="flex flex-wrap items-center gap-1 pt-2">
              {agent ? (
                <Tag
                  icon={SvgBubbleText}
                  title={agent.name}
                  truncate
                  tooltip={
                    defaultDisabled
                      ? "The agent for new chats."
                      : "The agent for new chats. Backspace in an empty input removes it."
                  }
                  onRemove={
                    defaultDisabled
                      ? undefined
                      : () => {
                          chooseAgent(null);
                          inputRef.current?.focus();
                        }
                  }
                  removeInTabOrder={false}
                />
              ) : null}
              {attachments.map((a) => (
                <Tag
                  key={a.key}
                  icon={a.isImage ? SvgImage : SvgPaperclip}
                  title={a.file === null && a.error === null ? `${a.name} (uploading…)` : a.name}
                  truncate
                  error={a.error !== null}
                  tooltip={a.error ?? undefined}
                  onRemove={() => {
                    removeAttachment(a.key);
                    inputRef.current?.focus();
                  }}
                  removeInTabOrder={false}
                />
              ))}
            </div>
          ) : null}
          {mode === "ask" && attachmentErrors.length > 0 ? (
            <div className="pt-1">
              <Text font="secondary-body" color="text-04">
                {attachmentErrors.join(" ")}
              </Text>
            </div>
          ) : null}
        </div>
        <div
          ref={resultsRef}
          className="selectable flex-1 overflow-y-auto border-t border-border-01 p-4"
        >
          {pickerOpen ? (
            <AgentPicker
              agents={pickerMatches}
              highlighted={highlighted?.id ?? null}
              selected={agentId}
              onPick={pickAgent}
            />
          ) : mode === "ask" ? (
            <ChatView turns={turns} />
          ) : (
            <SearchView
              hits={hits}
              searching={searching}
              error={searchError}
              sources={sources}
              sourceFilter={sourceFilter}
              onToggleSource={toggleSource}
            />
          )}
        </div>
        <div className="border-t border-border-01 px-4 py-2">
          <Text font="secondary-body" color="text-02">
            {notice ??
              hint({
                mode,
                pickerOpen,
                hasAnswer: answer !== null,
                hasCitations: (lastTurn?.citations.length ?? 0) > 0,
                hasHits: !searching && (hits?.length ?? 0) > 0,
                hasAgents: agents.length > 0,
                hasAttachments: attachments.length > 0,
              })}
          </Text>
        </div>
      </Section>
    </div>
  );
}

interface HintState {
  mode: Mode;
  pickerOpen: boolean;
  hasAnswer: boolean;
  hasCitations: boolean;
  hasHits: boolean;
  hasAgents: boolean;
  hasAttachments: boolean;
}

function hint(state: HintState): string {
  if (state.pickerOpen) return "↑↓ choose · Enter picks the agent · Esc cancels";
  if (state.mode === "search") {
    return state.hasHits
      ? `${primaryShortcut("1–9")} opens a result · ${primaryShortcut("Shift+1–9")} copies its link · ${primaryShortcut("C")} copies the selected result's link`
      : "Enter searches";
  }
  if (state.hasAnswer) {
    const parts = [`${primaryShortcut("C")} copies the answer`];
    if (state.hasCitations) parts.push(`${primaryShortcut("1–9")} opens source [n]`, `${primaryShortcut("Shift+1–9")} copies its link`);
    return parts.join(" · ");
  }
  const files = state.hasAttachments
    ? "Backspace in an empty input removes the last file"
    : "Paste or drop files to attach them";
  return state.hasAgents ? `@ or ${primaryShortcut("K")} picks an agent · ${files}` : files;
}

// A local window cannot follow links itself; they open through the app, which
// opens web links and server paths only. Other links show as plain text.
const OPENABLE_LINK = /^(https?:|\/)/i;

const ANSWER_COMPONENTS: CompactMarkdownProps["components"] = {
  a: ({ children, href }) =>
    href && OPENABLE_LINK.test(href) ? (
      <a
        href={href}
        data-link={href}
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

interface AgentPickerProps {
  agents: Agent[];
  highlighted: number | null;
  selected: number | null;
  onPick: (agent: Agent) => void;
}

const AGENT_LIST_ID = "launcher-agent-list";

function agentOptionId(id: number): string {
  return `launcher-agent-${id}`;
}

// The input keeps focus and names the highlighted option (aria-activedescendant).
function AgentPicker({ agents, highlighted, selected, onPick }: AgentPickerProps) {
  if (agents.length === 0) {
    return (
      <Text font="main-ui-muted" color="text-02">
        No matching agents.
      </Text>
    );
  }
  return (
    <div id={AGENT_LIST_ID} role="listbox" aria-label="Agents">
      <Section gap={1} alignItems="stretch" justifyContent="start" height="fit">
        {agents.map((a) => (
          <LineItemButton
            key={a.id}
            id={agentOptionId(a.id)}
            data-agent-id={a.id}
            presentational
            role="option"
            aria-selected={a.id === highlighted}
            state={a.id === highlighted ? "selected" : "empty"}
            title={a.name}
            description={a.description || undefined}
            descriptionMaxLines={1}
            suffix={a.id === (selected ?? DEFAULT_AGENT_ID) ? "Current" : undefined}
            // The input keeps focus, so typing still filters the list.
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onPick(a)}
          />
        ))}
      </Section>
    </div>
  );
}

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
      {turn.files.length > 0 ? (
        <Text font="secondary-body" color="text-03">
          {`Attached: ${turn.files.join(", ")}`}
        </Text>
      ) : null}
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
              data-link={citation.link ?? undefined}
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
  sources: string[];
  sourceFilter: string | null;
  onToggleSource: (source: string) => void;
}

function SearchView({
  hits,
  searching,
  error,
  sources,
  sourceFilter,
  onToggleSource,
}: SearchViewProps) {
  // Filters show once results come from more than one source, and stay while one is on.
  const filters =
    sources.length > 1 || sourceFilter !== null ? (
      <div className="flex flex-wrap gap-1 pb-3">
        {sources.map((source) => (
          <Tag
            key={source}
            title={sourceLabel(source)}
            aria-pressed={sourceFilter === source}
            onClick={() => onToggleSource(source)}
          />
        ))}
      </div>
    ) : null;
  let body;
  if (error) {
    body = (
      <Text font="main-ui-body" color="text-04">
        {error}
      </Text>
    );
  } else if (searching) {
    body = (
      <Text font="main-ui-muted" color="text-02">
        Searching…
      </Text>
    );
  } else if (hits === null) {
    body = (
      <Text font="main-ui-muted" color="text-02">
        Press Enter to search connected sources.
      </Text>
    );
  } else if (hits.length === 0) {
    body = (
      <Text font="main-ui-muted" color="text-02">
        No documents matched.
      </Text>
    );
  } else {
    body = (
      <Section gap={1} alignItems="stretch" justifyContent="start" height="fit">
        {hits.map((hit) => (
          <LineItemButton
            key={hit.documentId}
            title={hit.title}
            description={`${sourceLabel(hit.sourceType)} · ${hit.blurb}`}
            data-link={hit.link ?? undefined}
            onClick={() => hit.link && void openExternal(hit.link)}
          />
        ))}
      </Section>
    );
  }
  return (
    <>
      {filters}
      {body}
    </>
  );
}

mount(<Launcher />, "launcher");
