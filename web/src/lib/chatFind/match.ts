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
import { MENTION_TRIGGER, placeMentions } from "@/lib/chat/mentions";
import type { ComposedMention } from "@/lib/chat/types";
import { readToolQuestions } from "@/lib/chat/toolApprovals";

/**
 * The `data-chat-find-text` value of a message's text: a user row's text or
 * an agent message's answer text.
 */
export function chatFindTextKey(
  kind: "user" | "answer",
  nodeId: number
): string {
  return `${kind}:${nodeId}`;
}

/** The `data-chat-find-text` value of a user message shown inside a reply. */
export function chatFindInlineKey(nodeId: number, messageId: string): string {
  return `inline:${nodeId}:${messageId}`;
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
// Not searched: math and citation chips render other text, footnotes are
// left out on the page too, and the rest render none.
const SKIPPED_TYPES = new Set([
  "definition",
  "footnoteDefinition",
  "footnoteReference",
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
    // Raw HTML shows as its source text.
    if (
      node.type === "text" ||
      node.type === "inlineCode" ||
      node.type === "html"
    ) {
      text += (node.value ?? "").replace(/\r?\n/g, " ");
    }
    for (const child of node.children ?? []) visit(child);
    if (block) flush();
  };
  visit(tree);
  flush();
  return segments;
}

/** One searched text of a message, in the order the message shows them. */
interface MessagePart {
  turn: number;
  /** The `data-chat-find-text` value of the text on the page. */
  scopeKey: string;
  segments: string[];
}

/** The user's text as the bubble shows it: each mention is its own chip. */
function userSegments(
  text: string,
  mentions: readonly ComposedMention[] | undefined
): string[] {
  const segments: string[] = [];
  let start = 0;
  for (const mention of placeMentions(text, mentions ?? [])) {
    segments.push(text.slice(start, mention.index));
    segments.push(`${MENTION_TRIGGER}${mention.name}`);
    start = mention.index + MENTION_TRIGGER.length + mention.name.length;
  }
  segments.push(text.slice(start));
  return segments
    .map((segment) => segment.replace(/\r?\n/g, " "))
    .filter((segment) => segment.length > 0);
}

/**
 * The texts of an agent message: its answer text, and the messages the user
 * sent during the reply (also typed answers to its questions), which the
 * reply shows in place.
 */
function agentMessageParts(message: Message): MessagePart[] {
  const answers = new Map<string, MessagePart & { text: string }>();
  const parts: MessagePart[] = [];
  const userTurns = new Set<number>();
  for (const { obj, placement } of message.packets) {
    if (obj.type === PacketType.USER_MESSAGE) {
      userTurns.add(placement.turn_index);
      parts.push({
        turn: placement.turn_index,
        scopeKey: chatFindInlineKey(message.nodeId, obj.id),
        segments: userSegments(obj.message, obj.mentions),
      });
      continue;
    }
    if (
      obj.type !== PacketType.MESSAGE_START &&
      obj.type !== PacketType.MESSAGE_DELTA
    ) {
      continue;
    }
    const key = `${placement.turn_index}:${placement.tab_index ?? 0}`;
    const answer = answers.get(key);
    if (answer) answer.text += obj.content;
    else {
      answers.set(key, {
        turn: placement.turn_index,
        scopeKey: chatFindTextKey("answer", message.nodeId),
        segments: [],
        text: obj.content,
      });
    }
  }
  for (const { turnIndex, request, resolution } of readToolQuestions(
    message.packets
  ).entries) {
    const text = resolution?.outcome === "answered" ? resolution.message : null;
    if (!text || userTurns.has(turnIndex)) continue;
    parts.push({
      turn: turnIndex,
      scopeKey: chatFindInlineKey(
        message.nodeId,
        `question:${request.question_request_id}`
      ),
      segments: userSegments(text, []),
    });
  }
  // A user message opens its section, so it comes before text of its turn.
  for (const { text, ...answer } of answers.values()) {
    parts.push({ ...answer, segments: cachedAnswerSegments(text) });
  }
  return parts
    .map((part, order) => ({ part, order }))
    .sort((a, b) => a.part.turn - b.part.turn || a.order - b.order)
    .map(({ part }) => part);
}

// Packets grow in place while a reply streams, so the count keys the entry.
const partsByMessage = new WeakMap<
  Message,
  { packetCount: number; parts: MessagePart[] }
>();

function cachedAgentMessageParts(message: Message): MessagePart[] {
  const cached = partsByMessage.get(message);
  if (cached?.packetCount === message.packets.length) return cached.parts;
  const parts = agentMessageParts(message);
  partsByMessage.set(message, { packetCount: message.packets.length, parts });
  return parts;
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

/** One searched text of the chat. */
export interface ChatFindText {
  scopeKey: string;
  /** DOM id of the row that shows the text. */
  rowId: string;
  /** Index of the row's message in the chat. */
  messageIndex: number;
  segments: string[];
}

/**
 * The searchable text of the chat, in the order it shows: the user's text
 * and the agent's answer text. Tool steps and thinking are not searched.
 */
export function chatFindTexts(
  messages: readonly Message[],
  messageTree: Map<number, Message> | null | undefined
): ChatFindText[] {
  const texts: ChatFindText[] = [];
  const addAgentMessage = (
    message: Message,
    rowId: string,
    messageIndex: number
  ) => {
    for (const { scopeKey, segments } of cachedAgentMessageParts(message)) {
      texts.push({ scopeKey, rowId, messageIndex, segments });
    }
  };
  messages.forEach((message, messageIndex) => {
    const rowId = messageRowId(message);
    if (message.type === "user") {
      texts.push({
        scopeKey: chatFindTextKey("user", message.nodeId),
        rowId,
        messageIndex,
        segments: userSegments(message.message, message.mentions),
      });
      // Every answer of a multi-model turn shows in its question's row.
      const answers = messageTree
        ? getMultiModelChildren(message, messageTree)
        : null;
      for (const answer of answers ?? []) {
        addAgentMessage(answer, rowId, messageIndex);
      }
      return;
    }
    if (message.type !== "assistant" && message.type !== "error") return;
    const previous = messages[messageIndex - 1];
    if (
      previous?.type === "user" &&
      messageTree &&
      getMultiModelChildren(previous, messageTree)
    ) {
      return;
    }
    addAgentMessage(message, rowId, messageIndex);
  });
  return texts;
}

/** The matches of one searched text, in chat order. */
export interface ChatFindEntry {
  scopeKey: string;
  rowId: string;
  messageIndex: number;
  /** Index of the entry's first match among all matches. */
  start: number;
  count: number;
  /** Index of the entry's first match among its scope's matches. */
  occurrenceStart: number;
}

export interface ChatFindMatch {
  scopeKey: string;
  rowId: string;
  /** The match's index among its scope's matches on the page. */
  occurrence: number;
}

export interface ChatFindResults {
  entries: ChatFindEntry[];
  total: number;
}

/** Counts the matches of `query` in each searched text. */
export function findChatMatches(
  texts: readonly ChatFindText[],
  query: string
): ChatFindResults {
  const entries: ChatFindEntry[] = [];
  const scopeCounts = new Map<string, number>();
  let total = 0;
  if (!query) return { entries, total };
  for (const { segments, ...text } of texts) {
    let count = 0;
    for (const segment of segments) {
      count += findOccurrences(segment, query).length;
    }
    if (count === 0) continue;
    const occurrenceStart = scopeCounts.get(text.scopeKey) ?? 0;
    scopeCounts.set(text.scopeKey, occurrenceStart + count);
    entries.push({ ...text, start: total, count, occurrenceStart });
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
    scopeKey: entry.scopeKey,
    rowId: entry.rowId,
    occurrence: entry.occurrenceStart + index - entry.start,
  };
}
