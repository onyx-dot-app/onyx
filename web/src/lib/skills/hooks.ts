import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type SyntheticEvent,
} from "react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  caretTokenMayContain,
  getCaretRect,
  getTextBeforeCursor,
} from "@/lib/contentEditable";
import type { PickerEntry, PickerSkill } from "@/lib/skills/picker";
import {
  INITIAL_PICKER_SESSION,
  reduceOnDismiss,
  reduceOnInput,
  reduceOnSelection,
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

/** The custom skills that the user's chat agents get (`GET /api/skills/chat`),
 * as `@` picker entries, sorted by name. */
export function useChatSkills(): PickerSkill[] {
  const { user } = useUser();
  const { data } = useSWR<ChatSkill[]>(
    user ? SWR_KEYS.chatSkills : null,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );
  return useMemo(
    () =>
      (data ?? []).map(
        (skill): PickerSkill => ({
          kind: "skill",
          slug: skill.name,
          name: skill.name,
          description: skill.description,
        })
      ),
    [data]
  );
}

interface UseEntryPickerOptions {
  /** Called when the user picks an entry. The caller replaces `token` (the
   * trigger and query before the caret) with the entry, e.g. as a chip. */
  onSelect: (entry: PickerEntry, token: string) => void;
  /** The character that opens the picker. */
  trigger: string;
}

export interface UseEntryPickerResult {
  open: boolean;
  query: string;
  anchorRect: DOMRect | null;
  onSelect: (entry: PickerEntry) => void;
  onClose: () => void;
  reset: () => void;
  onInput: (event: SyntheticEvent<HTMLElement>) => void;
  onSelectionChange: (event: SyntheticEvent<HTMLElement>) => void;
}

/** Drives the trigger-character entry picker over a contentEditable input.
 * The host forwards the input's events; their `currentTarget` is read for the
 * text before the caret and the caret position. */
export function useEntryPicker({
  onSelect,
  trigger,
}: UseEntryPickerOptions): UseEntryPickerResult {
  const [session, setSession] = useState<PickerSession>(INITIAL_PICKER_SESSION);
  // Mirror into a ref so the returned handlers keep a stable identity.
  const sessionRef = useRef(session);
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);

  useEffect(() => {
    sessionRef.current = session;
  }, [session]);

  const reset = useCallback(() => setSession(INITIAL_PICKER_SESSION), []);
  const onClose = useCallback(() => setSession(reduceOnDismiss), []);

  const onInput = useCallback(
    (event: SyntheticEvent<HTMLElement>) => {
      const input = event.currentTarget;
      // Reading the text before the caret clones the DOM. Without a session,
      // only a token that holds the trigger can open one.
      if (
        sessionRef.current.triggerIndex === null &&
        !caretTokenMayContain(input, trigger)
      )
        return;
      const next = reduceOnInput(
        sessionRef.current,
        getTextBeforeCursor(input),
        trigger
      );
      if (next.open) setAnchorRect(getCaretRect(input));
      setSession(next);
    },
    [trigger]
  );

  // Re-sync (or close) the picker after the caret moves (arrow keys, click).
  const onSelectionChange = useCallback(
    (event: SyntheticEvent<HTMLElement>) => {
      const current = sessionRef.current;
      if (!current.open) return;
      const input = event.currentTarget;
      const next = reduceOnSelection(
        current,
        getTextBeforeCursor(input),
        trigger
      );
      if (next.open) setAnchorRect(getCaretRect(input));
      setSession(next);
    },
    [trigger]
  );

  const handleSelect = useCallback(
    (entry: PickerEntry) => {
      const current = sessionRef.current;
      if (!current.open) return;
      onSelect(entry, `${trigger}${current.query}`);
      reset();
    },
    [onSelect, reset, trigger]
  );

  return {
    open: session.open,
    query: session.query,
    anchorRect,
    onSelect: handleSelect,
    onClose,
    reset,
    onInput,
    onSelectionChange,
  };
}
