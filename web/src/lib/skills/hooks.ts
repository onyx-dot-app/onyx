import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type SyntheticEvent,
} from "react";
import useSWR, { useSWRConfig } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { getTextAroundCursor, type CaretText } from "@/lib/contentEditable";
import {
  flattenSections,
  type PickerEntry,
  type PickerSections,
  type PickerSkill,
} from "@/lib/skills/picker";
import {
  INITIAL_PICKER_SESSION,
  reduceOnEscape,
  reduceOnInput,
  type PickerSession,
} from "@/lib/skills/pickerSession";
import type { ChatSkill } from "@/lib/skills/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { useUser } from "@/providers/UserProvider";
import { useSettings } from "@/lib/settings/hooks";
import { PluginPublishingPolicy } from "@/lib/settings/types";
import { Permission } from "@/lib/types";

export type PublishAction = "publish" | "review" | "off";

/** What publishing a skill does for the current user. */
export function usePublishAction(): PublishAction {
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_PLUGINS);
  const { plugin_publishing: policy } = useSettings();
  if (isGlobalHolder) return "publish";
  if (policy === PluginPublishingPolicy.REQUIRES_REVIEW) return "review";
  if (policy === PluginPublishingPolicy.OFF) return "off";
  return "publish";
}

export interface ChatSkillEntries {
  /** The skills as `@` picker sections, sorted by name. */
  entries: PickerSections;
  /** Call when the chat input gains focus. Fetches the skills again unless a
   * fetch is running or this fetched within SWR's focus throttle interval. */
  onInputFocus: () => void;
}

/** The custom skills that the user's chat agents get (`GET /api/skills/chat`).
 * Skill changes made in this app fetch them again (`lib/skills/cache.ts`).
 * Changes from elsewhere show after the chat input gains focus; a window
 * focus does not fetch them. */
export function useChatSkills(): ChatSkillEntries {
  const { user } = useUser();
  const { focusThrottleInterval } = useSWRConfig();
  const { data, mutate, isValidating } = useSWR<ChatSkill[]>(
    user ? SWR_KEYS.chatSkills : null,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );
  const lastFocusFetchRef = useRef(0);
  const onInputFocus = useCallback(() => {
    const now = Date.now();
    if (isValidating || now - lastFocusFetchRef.current < focusThrottleInterval)
      return;
    lastFocusFetchRef.current = now;
    void mutate();
  }, [isValidating, focusThrottleInterval, mutate]);
  const entries = useMemo(
    (): PickerSections => ({
      skills: (data ?? []).map(
        (skill): PickerSkill => ({
          kind: "skill",
          slug: skill.name,
          name: skill.name,
          description: skill.short_description ?? skill.description,
        })
      ),
      apps: [],
      mcpServers: [],
    }),
    [data]
  );
  return { entries, onInputFocus };
}

interface UseEntryPickerOptions {
  /** The character that opens the picker. */
  trigger: string;
  /** Everything the picker can offer. Memoize it: a new identity matches the
   * open query again. */
  entries: PickerSections;
  /** The `entries` that match a query; a module-level function, so its
   * identity is stable. A word that matches none ends the session. */
  filter: (entries: PickerSections, query: string) => PickerSections;
  /** Called when the user picks an entry. The caller replaces `token` (the
   * trigger and its whole word, split at the caret) with the entry, e.g. as a
   * chip. The caret is still where the last input left it. */
  onSelect: (entry: PickerEntry, token: CaretText) => void;
}

export interface UseEntryPickerResult {
  open: boolean;
  query: string;
  /** The entries that match `query`. */
  sections: PickerSections;
  anchorRect: DOMRect | null;
  onSelect: (entry: PickerEntry) => void;
  /** Esc: hide the picker until the trigger is deleted. */
  onEscape: () => void;
  /** End the session; the next input in the word can open it again. */
  reset: () => void;
  /** The input's input (or textarea change) handler. */
  onInput: (event: SyntheticEvent<HTMLElement>) => void;
}

/** A collapsed caret in `input`, a contentEditable or a focused textarea. */
function readCaret(input: HTMLElement): { node: Node; offset: number } | null {
  if (input instanceof HTMLTextAreaElement) {
    return document.activeElement === input &&
      input.selectionStart === input.selectionEnd
      ? { node: input, offset: input.selectionStart }
      : null;
  }
  const selection = window.getSelection();
  const range =
    selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;
  return range?.collapsed && input.contains(range.startContainer)
    ? { node: range.startContainer, offset: range.startOffset }
    : null;
}

/** Drives the trigger-character entry picker over a contentEditable input or
 * a textarea. The host forwards the input's input events; their
 * `currentTarget` is read for the text around the caret and the caret
 * position. Only input opens the picker or changes its query. Any selection
 * change that leaves the caret elsewhere than the last input put it ends the
 * session. When `entries` change while open, the query is matched again, and a
 * query that matches nothing ends the session. */
export function useEntryPicker({
  trigger,
  entries,
  filter,
  onSelect,
}: UseEntryPickerOptions): UseEntryPickerResult {
  const [session, setSession] = useState<PickerSession>(INITIAL_PICKER_SESSION);
  // The latest session, which handlers read before React renders it.
  const sessionRef = useRef(session);
  // The input and where its last input left the caret.
  const caretRef = useRef<{
    input: HTMLElement;
    node: Node;
    offset: number;
  } | null>(null);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  const hasEntries = useMemo(
    () => flattenSections(entries).length > 0,
    [entries]
  );

  const commit = useCallback((next: PickerSession) => {
    sessionRef.current = next;
    setSession(next);
  }, []);
  const reset = useCallback(() => commit(INITIAL_PICKER_SESSION), [commit]);
  const onEscape = useCallback(
    () => commit(reduceOnEscape(sessionRef.current)),
    [commit]
  );

  const onInput = useCallback(
    (event: SyntheticEvent<HTMLElement>) => {
      if (!hasEntries) return;
      const input = event.currentTarget;
      let text: CaretText | null;
      if (input instanceof HTMLTextAreaElement) {
        const caret = input.selectionStart;
        const tail = input.value.slice(caret);
        text = {
          before: input.value.slice(0, caret),
          after: tail.slice(0, tail.search(/\s|$/)),
        };
      } else {
        // Reading the text around the caret clones the DOM. Without a
        // session, skip it unless the caret's word can hold the trigger: the
        // word before the caret in its text node holds it, or the word can
        // start in an earlier node.
        if (sessionRef.current.triggerIndex === null) {
          const caret = readCaret(input);
          if (!caret) return;
          if (caret.node.nodeType === Node.TEXT_NODE) {
            const before = (caret.node.textContent ?? "").slice(
              0,
              caret.offset
            );
            const wordStart = before.search(/\S*$/);
            const startsEarlier =
              wordStart === 0 &&
              (caret.node.previousSibling !== null ||
                caret.node.parentNode !== input);
            if (!startsEarlier && !before.slice(wordStart).includes(trigger))
              return;
          }
        }
        text = getTextAroundCursor(input);
      }
      const next = reduceOnInput(sessionRef.current, text, trigger, (query) =>
        filter(entries, query)
      );
      if (next.open) {
        const caret = readCaret(input);
        caretRef.current = caret && { input, ...caret };
        // A textarea anchors at itself. A caret on an empty line has an
        // empty rect, so it anchors at the input too.
        let rect = input.getBoundingClientRect();
        if (caret && !(input instanceof HTMLTextAreaElement)) {
          const range = document.createRange();
          range.setStart(caret.node, caret.offset);
          const caretRect = range.getBoundingClientRect();
          if (
            caretRect.top ||
            caretRect.left ||
            caretRect.width ||
            caretRect.height
          )
            rect = caretRect;
        }
        setAnchorRect(rect);
      }
      commit(next);
    },
    [hasEntries, trigger, filter, entries, commit]
  );

  // Entries can change while open, for example on revalidation.
  useEffect(() => {
    const current = sessionRef.current;
    if (!current.open) return;
    const sections = filter(entries, current.query);
    commit(
      flattenSections(sections).length > 0
        ? { ...current, sections }
        : INITIAL_PICKER_SESSION
    );
  }, [entries, filter, commit]);

  // `selectionchange` follows every caret move, including the one an input
  // makes, so only a caret that left the place where the last input put it
  // ends the session. Text controls fire it at the element, so listen in the
  // capture phase.
  useEffect(() => {
    if (!session.open) return;
    function handleSelectionChange() {
      const last = caretRef.current;
      const caret = last && readCaret(last.input);
      if (caret && caret.node === last?.node && caret.offset === last.offset)
        return;
      commit(INITIAL_PICKER_SESSION);
    }
    document.addEventListener("selectionchange", handleSelectionChange, true);
    return () =>
      document.removeEventListener(
        "selectionchange",
        handleSelectionChange,
        true
      );
  }, [session.open, commit]);

  const handleSelect = useCallback(
    (entry: PickerEntry) => {
      const current = sessionRef.current;
      if (!current.open) return;
      onSelect(entry, current.token);
      reset();
    },
    [onSelect, reset]
  );

  return {
    open: session.open,
    query: session.query,
    sections: session.sections,
    anchorRect,
    onSelect: handleSelect,
    onEscape,
    reset,
    onInput,
  };
}
