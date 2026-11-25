"use client";

// Adapted from T3 Code (MIT, github.com/pingdotgg/t3code).
import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { useTranslations } from "next-intl";
import { Button, InputTypeIn, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { useDebouncedValue, useHotkey } from "@opal/hooks";
import { SvgChevronDown, SvgChevronUp, SvgSearch, SvgX } from "@opal/icons";
import {
  useCurrentMessageHistory,
  useCurrentMessageTree,
} from "@/app/app/stores/useChatSessionStore";
import { useScrollContainer } from "@/lib/chatScroll/components/ScrollContainerContext";
import { useChatFindHighlights } from "@/lib/chatFind/hooks";
import {
  chatFindMatchAt,
  chatFindTexts,
  findChatMatches,
  stepChatFindIndex,
  type ChatFindResults,
} from "@/lib/chatFind/match";
import {
  closeChatFind,
  openChatFind,
  setChatFindQuery,
  useChatFindStore,
} from "@/lib/chatFind/store";
import { messageRowId } from "@/lib/chat/rowIds";
import { CHAT_SHORTCUTS } from "@/lib/shortcuts/constants";
import { isModalOpen } from "@/lib/shortcuts/utils";

const FIND_DEBOUNCE_MS = 100;
const NO_RESULTS: ChatFindResults = { entries: [], total: 0 };

/**
 * Find in the shown chat: Ctrl+F (⌘F on macOS) opens a bar over the chat
 * that searches every loaded message, also the rows the list has unmounted.
 * Render it in the chat's `ChatScrollContainer` overlay.
 */
export default function ChatFind() {
  const open = useChatFindStore((state) => state.open);
  const { sessionId } = useScrollContainer();

  useHotkey(CHAT_SHORTCUTS.find, openChatFind, {
    whileTyping: true,
    shouldHandle: () => !isModalOpen(),
  });
  // Find belongs to the chat it was opened in.
  useEffect(() => () => closeChatFind(), [sessionId]);

  return open ? <ChatFindBar /> : null;
}

/** The index of the first message at the top of the view. */
function topMessageIndex(
  container: HTMLElement | null,
  rowIds: readonly string[]
): number {
  if (!container) return 0;
  const viewportTop = container.getBoundingClientRect().top;
  for (const row of Array.from(
    container.querySelectorAll<HTMLElement>('[id^="message-"]')
  )) {
    if (row.getBoundingClientRect().bottom > viewportTop) {
      return Math.max(0, rowIds.indexOf(row.id));
    }
  }
  return 0;
}

function ChatFindBar() {
  const t = useTranslations("chat.find");
  const { scrollContainerRef, releaseFollowing } = useScrollContainer();
  const query = useChatFindStore((state) => state.query);
  const focusRequestId = useChatFindStore((state) => state.focusRequestId);
  const messages = useCurrentMessageHistory();
  const messageTree = useCurrentMessageTree();
  const barRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  const searchedQuery = useDebouncedValue(query.trim(), FIND_DEBOUNCE_MS);
  const results = useMemo(
    () =>
      searchedQuery
        ? findChatMatches(chatFindTexts(messages, messageTree), searchedQuery)
        : NO_RESULTS,
    [messages, messageTree, searchedQuery]
  );

  // A new search starts at the view; a step picks an index. Each one gets a
  // new id, so its match is brought into view even when it is the same one.
  const [selection, setSelection] = useState<{
    fromMessage: number;
    index: number | null;
    id: number;
  }>({ fromMessage: 0, index: null, id: 0 });
  const startIndex =
    results.entries.find((entry) => entry.messageIndex >= selection.fromMessage)
      ?.start ?? 0;
  const activeIndex =
    results.total === 0
      ? 0
      : Math.min(selection.index ?? startIndex, results.total - 1);
  const match = chatFindMatchAt(results.entries, activeIndex);
  // While a typed query waits for its search, the old results show but are
  // not brought into view.
  const searchPending = searchedQuery !== query.trim();
  const matchKey =
    match && !searchPending
      ? `${selection.id}:${searchedQuery}:${match.scopeKey}:${match.occurrence}`
      : null;

  useChatFindHighlights({
    scrollContainerRef,
    releaseFollowing,
    query: searchedQuery,
    match,
    matchKey,
  });

  useEffect(() => {
    const focused = document.activeElement;
    if (
      focused instanceof HTMLElement &&
      focused !== document.body &&
      !barRef.current?.contains(focused)
    ) {
      returnFocusRef.current = focused;
    }
    inputRef.current?.focus();
    inputRef.current?.select();
  }, [focusRequestId]);

  function handleQueryChange(value: string) {
    setChatFindQuery(value);
    setSelection((previous) => ({
      fromMessage: topMessageIndex(
        scrollContainerRef.current,
        messages.map(messageRowId)
      ),
      index: null,
      id: previous.id + 1,
    }));
  }

  function step(delta: number) {
    if (results.total === 0) return;
    setSelection((previous) => ({
      ...previous,
      index: stepChatFindIndex(activeIndex, results.total, delta),
      id: previous.id + 1,
    }));
  }

  function close() {
    const returnFocus = returnFocusRef.current;
    closeChatFind();
    if (returnFocus?.isConnected) returnFocus.focus();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing) return;
    if (event.key === "Enter") {
      event.preventDefault();
      step(event.shiftKey ? -1 : 1);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close();
    }
  }

  const hasQuery = query.trim().length > 0;
  const navigationDisabled = results.total === 0;

  return (
    <div
      ref={barRef}
      role="search"
      aria-label={t("label")}
      className="absolute top-3 end-3 z-sticky w-[min(24rem,calc(100%-1.5rem))] rounded-08 shadow-box-01"
    >
      <InputTypeIn
        ref={inputRef}
        icon={SvgSearch}
        value={query}
        onChange={(event) => handleQueryChange(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={t("placeholder")}
        aria-label={t("label")}
        maxLength={200}
        spellCheck={false}
        autoComplete="off"
        rightChildren={
          <Section flexDirection="row" width="fit" gap={0} alignItems="center">
            <span aria-live="polite">
              {hasQuery && (
                <Text
                  font="secondary-body"
                  color={navigationDisabled ? "status-error-05" : "text-03"}
                >
                  {t("count", {
                    current: results.total === 0 ? 0 : activeIndex + 1,
                    total: results.total,
                  })}
                </Text>
              )}
            </span>
            <Button
              icon={SvgChevronUp}
              prominence="tertiary"
              size="sm"
              aria-label={t("previous")}
              tooltip={t("previous")}
              disabled={navigationDisabled}
              onClick={() => step(-1)}
            />
            <Button
              icon={SvgChevronDown}
              prominence="tertiary"
              size="sm"
              aria-label={t("next")}
              tooltip={t("next")}
              disabled={navigationDisabled}
              onClick={() => step(1)}
            />
            <Button
              icon={SvgX}
              prominence="tertiary"
              size="sm"
              aria-label={t("close")}
              tooltip={t("close")}
              onClick={close}
            />
          </Section>
        }
      />
    </div>
  );
}
