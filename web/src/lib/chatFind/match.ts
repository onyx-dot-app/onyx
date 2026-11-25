// Adapted from T3 Code (MIT, github.com/pingdotgg/t3code).
import { unified } from "unified";
import remarkParse from "remark-parse";
import type { Message } from "@/app/app/types";
import { PacketType } from "@/app/app/services/streamingModels";
import { prepareAnswerMarkdown } from "@/lib/answerText/utils";
import { ANSWER_REMARK_PLUGINS } from "@/lib/answerText/remarkPlugins";
import type { MarkdownAstNode } from "@/lib/answerText/remarkGithubAlerts";
import { stripPartialCitations } from "@/lib/timeline/chat/message/messageComponents/markdownUtils";
import { getMultiModelChildren } from "@/lib/timeline/chat/message/multiModel";
import { messageRowId } from "@/lib/chat/rowIds";

/** Which text of a message find searches: the question or the answer. */
export type ChatFindKind = "user" | "answer";

/** The matches of one message, in chat order. */
export interface ChatFindEntry {
  nodeId: number;
  /** DOM id of the row that shows the message. */
  rowId: string;
  /** Index of the message in the chat. */
  messageIndex: number;
  kind: ChatFindKind;
  /** Index of the message's first match among all matches. */
  start: number;
  count: number;
}

export interface ChatFindMatch {
  nodeId: number;
  rowId: string;
  kind: ChatFindKind;
  /** The match's index among its message's matches. */
  occurrence: number;
}

// A typed straight apostrophe finds a curly one: iOS keyboards type "’".
const foldCharacters = (text: string) =>
  text.replace(/ς/g, "σ").replace(/[‘’]/g, "'");

function foldCase(text: string): string {
  const lowered = foldCharacters(text.toLowerCase());
  if (lowered.length === text.length) return lowered;
  let folded = "";
  for (const character of text) {
    // Lowercasing İ adds a combining dot. Drop it to keep source offsets.
    const loweredCharacter = foldCharacters(character.toLowerCase()).replace(
      "i̇",
      "i"
    );
    folded +=
      loweredCharacter.length === character.length
        ? loweredCharacter
        : character;
  }
  return folded;
}

/** Start offsets of the non-overlapping, case-insensitive matches of `query`. */
export function findOccurrences(text: string, query: string): number[] {
  const offsets: number[] = [];
  if (text.length === 0 || query.length === 0) return offsets;
  const foldedText = foldCase(text);
  const foldedQuery = foldCase(query);
  let cursor = 0;
  while (cursor <= foldedText.length - foldedQuery.length) {
    const offset = foldedText.indexOf(foldedQuery, cursor);
    if (offset === -1) break;
    offsets.push(offset);
    cursor = offset + foldedQuery.length;
  }
  return offsets;
}

export function stepChatFindIndex(
  index: number,
  total: number,
  delta: number
): number {
  if (total <= 0) return 0;
  const clamped = Math.min(Math.max(Math.trunc(index), 0), total - 1);
  return (((clamped + delta) % total) + total) % total;
}

// Same syntax as `AnswerMarkdown`.
const answerParser = unified().use(remarkParse).use(ANSWER_REMARK_PLUGINS);

// Rendered as their own block, so a match never spans them.
const BLOCK_TYPES = new Set([
  "blockquote",
  "break",
  "details",
  "heading",
  "list",
  "listItem",
  "paragraph",
  "table",
  "tableCell",
  "tableRow",
  "thematicBreak",
]);
// Not searched: math and citation chips render other text, and the rest
// render none.
const SKIPPED_TYPES = new Set([
  "definition",
  "footnoteReference",
  "html",
  "image",
  "imageReference",
  "inlineMath",
  "math",
]);
const CITATION_LABEL = /^\[(D|Q)?\d+\]$/;

function plainText(node: MarkdownAstNode): string {
  return node.value ?? (node.children ?? []).map(plainText).join("");
}

/**
 * The text runs of an answer as `AnswerMarkdown` shows them. A match never
 * spans two runs; the find highlights split the rendered text the same way.
 */
export function answerFindSegments(content: string): string[] {
  const tree: MarkdownAstNode = answerParser.runSync(
    answerParser.parse(prepareAnswerMarkdown(stripPartialCitations(content)))
  );
  const segments: string[] = [];
  let text = "";
  const flush = () => {
    if (text) segments.push(text);
    text = "";
  };
  const visit = (node: MarkdownAstNode) => {
    if (
      SKIPPED_TYPES.has(node.type) ||
      (node.type === "link" && CITATION_LABEL.test(plainText(node)))
    ) {
      flush();
      return;
    }
    if (node.type === "detailsSummary") {
      flush();
      const summary = (node.data?.hChildren ?? []).map((child) => child.value);
      if (summary.join("")) segments.push(summary.join(""));
      return;
    }
    if (node.type === "code") {
      flush();
      // A code block shows one row per line.
      for (const line of (node.value ?? "").split("\n")) {
        if (line) segments.push(line);
      }
      return;
    }
    const block = BLOCK_TYPES.has(node.type);
    if (block) flush();
    if (node.type === "text" || node.type === "inlineCode") {
      text += (node.value ?? "").replace(/\r?\n/g, " ");
    }
    for (const child of node.children ?? []) visit(child);
    if (block) flush();
  };
  visit(tree);
  flush();
  return segments;
}

// Packets grow in place while a reply streams, so the count keys the entry.
const answerSegmentsByMessage = new WeakMap<
  Message,
  { packetCount: number; segments: string[] }
>();

function messageAnswerSegments(message: Message): string[] {
  const cached = answerSegmentsByMessage.get(message);
  if (cached?.packetCount === message.packets.length) return cached.segments;
  const segments = answerTexts(message).flatMap(cachedAnswerSegments);
  answerSegmentsByMessage.set(message, {
    packetCount: message.packets.length,
    segments,
  });
  return segments;
}

/** The answer text of each block of an agent message, in order. */
function answerTexts(message: Message): string[] {
  const texts = new Map<string, string>();
  for (const packet of message.packets) {
    const { obj, placement } = packet;
    if (
      obj.type !== PacketType.MESSAGE_START &&
      obj.type !== PacketType.MESSAGE_DELTA
    ) {
      continue;
    }
    const key = `${placement.turn_index}:${placement.tab_index ?? 0}`;
    texts.set(key, (texts.get(key) ?? "") + obj.content);
  }
  return [...texts.values()];
}

// Parsing is the slow part, so the runs of each answer text are kept. Rows
// that stream reparse only their own text.
const answerSegmentCache = new Map<string, string[]>();
const ANSWER_SEGMENT_CACHE_SIZE = 500;

function cachedAnswerSegments(content: string): string[] {
  const cached = answerSegmentCache.get(content);
  if (cached) return cached;
  const segments = answerFindSegments(content);
  if (answerSegmentCache.size >= ANSWER_SEGMENT_CACHE_SIZE) {
    answerSegmentCache.clear();
  }
  answerSegmentCache.set(content, segments);
  return segments;
}

/** The searchable text of one message. */
export interface ChatFindText {
  nodeId: number;
  rowId: string;
  messageIndex: number;
  kind: ChatFindKind;
  segments: string[];
}

/**
 * The searchable text of the chat, one item per message: the user's text and
 * the agent's answer text. Tool steps and thinking are not searched.
 */
export function chatFindTexts(
  messages: readonly Message[],
  messageTree: Map<number, Message> | null | undefined
): ChatFindText[] {
  const texts: ChatFindText[] = [];
  messages.forEach((message, messageIndex) => {
    if (message.type === "user") {
      texts.push({
        nodeId: message.nodeId,
        rowId: messageRowId(message),
        messageIndex,
        kind: "user",
        segments: [message.message.replace(/\r?\n/g, " ")],
      });
      return;
    }
    if (message.type !== "assistant" && message.type !== "error") return;
    const previous = messages[messageIndex - 1];
    // A multi-model answer shows in its question's row.
    const row =
      previous?.type === "user" &&
      messageTree &&
      getMultiModelChildren(previous, messageTree)
        ? previous
        : message;
    texts.push({
      nodeId: message.nodeId,
      rowId: messageRowId(row),
      messageIndex,
      kind: "answer",
      segments: messageAnswerSegments(message),
    });
  });
  return texts;
}

/** Counts the matches of `query` in each message. */
export interface ChatFindResults {
  entries: ChatFindEntry[];
  total: number;
}

export function findChatMatches(
  texts: readonly ChatFindText[],
  query: string
): ChatFindResults {
  const entries: ChatFindEntry[] = [];
  let total = 0;
  if (!query) return { entries, total };
  for (const { segments, ...text } of texts) {
    let count = 0;
    for (const segment of segments) {
      count += findOccurrences(segment, query).length;
    }
    if (count === 0) continue;
    entries.push({ ...text, start: total, count });
    total += count;
  }
  return { entries, total };
}

/** The match at `index` among all matches. */
export function chatFindMatchAt(
  entries: readonly ChatFindEntry[],
  index: number
): ChatFindMatch | null {
  const entry = entries.find(
    (candidate) =>
      index >= candidate.start && index < candidate.start + candidate.count
  );
  if (!entry) return null;
  return {
    nodeId: entry.nodeId,
    rowId: entry.rowId,
    kind: entry.kind,
    occurrence: index - entry.start,
  };
}
