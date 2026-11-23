import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type SyntheticEvent,
} from "react";
import useSWR, { useSWRConfig, type KeyedMutator } from "swr";
import {
  errorHandlingFetcher,
  FetchError,
  fetchErrorDetail,
} from "@/lib/fetcher";
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
import { SWR_KEYS } from "@/lib/swr-keys";
import { useFormatBytes } from "@/hooks/useFormatBytes";
import { useTranslations } from "next-intl";
import {
  useCreateModal,
  type ModalCreationInterface,
  type SelectOption,
} from "@opal/components";
import { toast } from "@opal/layouts";
import {
  isSkillNameConflict,
  setSkillEnabled,
  skillNameConflictNames,
} from "@/lib/skills/api";
import { refreshSkillListsChecked } from "@/lib/skills/cache";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { useUser } from "@/providers/UserProvider";
import { useSettings } from "@/lib/settings/hooks";
import { PluginPublishingPolicy } from "@/lib/settings/types";
import { Permission } from "@/lib/types";
import {
  INHERIT,
  INSTALLATION_POLICIES,
  type InheritOption,
} from "@/lib/skills/installationPolicy";
import { skillLimitOf } from "@/lib/skills/limits";
import type {
  ChatSkill,
  Skill,
  SkillInstallationPolicy,
  SkillsList,
} from "@/lib/skills/types";

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

/** The composer takes focus again after each send, so a short interval would
 * fetch the chat skills on almost every turn. */
const CHAT_SKILLS_FOCUS_THROTTLE_MS = 60_000;

export interface ChatSkillEntries {
  /** The skills as `@` picker sections, sorted by name. */
  entries: PickerSections;
  /** Call when the chat input gains focus. Fetches the skills again unless a
   * fetch started within `CHAT_SKILLS_FOCUS_THROTTLE_MS`. Its identity is
   * stable. */
  onInputFocus: () => void;
}

/** The skills that the user's chat agents get (`GET /api/skills/chat`).
 * Skill changes made in this app fetch them again (`lib/skills/cache.ts`).
 * Changes from elsewhere show after the chat input gains focus; a window
 * focus does not fetch them. */
export function useChatSkills({
  builtIns,
}: {
  builtIns: boolean;
}): ChatSkillEntries {
  const { user } = useUser();
  // When the last fetch started, from any trigger.
  const lastFetchRef = useRef(0);
  const { data, mutate } = useSWR<ChatSkill[]>(
    user ? SWR_KEYS.chatSkills : null,
    (url: string) => {
      lastFetchRef.current = Date.now();
      return errorHandlingFetcher<ChatSkill[]>(url);
    },
    { revalidateOnFocus: false }
  );
  const onInputFocus = useCallback(() => {
    if (Date.now() - lastFetchRef.current < CHAT_SKILLS_FOCUS_THROTTLE_MS)
      return;
    void mutate();
  }, [mutate]);
  const entries = useMemo(
    (): PickerSections => ({
      skills: (data ?? [])
        .filter((skill) => builtIns || skill.built_in_skill_id === null)
        .map(
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
    [data, builtIns]
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
 * position. Only typing or deleting opens the picker or changes its query; a
 * paste or drop ends the session. Any selection change that leaves the caret
 * elsewhere than the last input put it ends the session. When `entries`
 * change while open, the query is matched again, and a query that matches
 * nothing ends the session. */
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
      // A paste, yank or drop is not typing, so like a caret move it closes
      // an open picker and keeps an Esc suppression.
      if (
        event.nativeEvent instanceof InputEvent &&
        /^insertFrom(Paste|Yank|Drop)/.test(event.nativeEvent.inputType)
      ) {
        if (sessionRef.current.open) commit(INITIAL_PICKER_SESSION);
        return;
      }
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
/** Sharing with people and groups is allowed for the current user: the admin
 * Sharing setting is on, or the user is an organization-wide skill manager. */
export function useSharingAllowed(): boolean {
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_PLUGINS);
  const { plugin_sharing: sharing } = useSettings();
  return isGlobalHolder || sharing !== false;
}

/** The one set of level labels and help text. ``null`` is "no own setting":
 * a group uses the Organization setting, and a skill uses Default access
 * (``inherit.policy``, when known, is the level it stands for). */
export function useInstallationPolicyCopy() {
  const t = useTranslations("skills.installationPolicy");
  return {
    label: (
      policy: SkillInstallationPolicy | null,
      inherit: InheritOption = { scope: "skill", policy: null }
    ) => {
      if (policy !== null) return t(`${policy}.label`);
      if (inherit.policy === null)
        return t("inherit.label", { scope: inherit.scope });
      return t("inherit.labelWithPolicy", {
        scope: inherit.scope,
        policy: t(`${inherit.policy}.label`),
      });
    },
    description: (
      policy: SkillInstallationPolicy | null,
      scope: InheritOption["scope"] = "skill"
    ) =>
      policy === null
        ? t("inherit.description", { scope })
        : t(`${policy}.description`),
  };
}

interface PolicyOptionsConfig {
  levels?: readonly SkillInstallationPolicy[];
  inherit?: InheritOption;
}

/** The select options of an install setting, with an optional "no own
 * setting" option first. */
export function usePolicyOptions({
  levels = INSTALLATION_POLICIES,
  inherit,
}: PolicyOptionsConfig = {}): SelectOption[] {
  const copy = useInstallationPolicyCopy();
  const options: SelectOption[] = levels.map((policy) => ({
    value: policy,
    title: copy.label(policy),
    description: copy.description(policy),
  }));
  if (!inherit) return options;
  return [
    {
      value: INHERIT,
      title: copy.label(null, inherit),
      description: copy.description(null, inherit.scope),
    },
    ...options,
  ];
}

export interface SkillLimitCopy {
  /** The refusal of a 413 SKILL_LIMIT_EXCEEDED error, else the server's
   * detail, else `fallback`. */
  describeError: (error: unknown, fallback: string) => string;
}

export function useSkillLimitCopy(): SkillLimitCopy {
  const t = useTranslations("skills.limit");
  const formatBytes = useFormatBytes();
  const describeError = useCallback(
    (error: unknown, fallback: string) => {
      const limit = skillLimitOf(error);
      if (limit !== null)
        return t("refused", {
          maxSize: formatBytes(limit.max_bytes),
          maxFiles: limit.max_files,
        });
      if (error instanceof FetchError)
        return fetchErrorDetail(error) ?? fallback;
      return error instanceof Error && error.message ? error.message : fallback;
    },
    [t, formatBytes]
  );
  return { describeError };
}

export interface SkillToggleTarget {
  id: string;
  name: string;
  enabled: boolean;
}

export interface SkillEnablement {
  setEnabled: (
    item: SkillToggleTarget,
    enabled: boolean,
    replaceConflict?: boolean
  ) => Promise<void>;
  isPending: (id: string) => boolean;
  /** The state to show: an in-flight change wins over the loaded one. */
  enabledOf: (item: SkillToggleTarget) => boolean;
  /** A skill whose name another enabled skill holds, waiting for a confirm. */
  switchTarget: SkillToggleTarget | null;
  /** The skills that the switch turns off. */
  switchConflicts: string[];
  switchModal: ModalCreationInterface;
}

/** Turns skills on and off. Only one enabled skill holds a name, so turning
 * on a skill whose name is taken asks first, then replaces the other one.
 * `onEnabled` gets the skill as the server returns it after a turn on. */
export function useSkillEnablement(
  items: readonly SkillToggleTarget[],
  refresh: KeyedMutator<SkillsList>,
  onEnabled?: (skill: Skill) => void
): SkillEnablement {
  const t = useTranslations("skills");
  const { describeError } = useSkillLimitCopy();
  const { mutate, cache } = useSWRConfig();
  const switchModal = useCreateModal();
  const [pending, setPending] = useState<ReadonlySet<string>>(new Set());
  const [optimistic, setOptimistic] = useState<ReadonlyMap<string, boolean>>(
    new Map()
  );
  const [switchTarget, setSwitchTarget] = useState<SkillToggleTarget | null>(
    null
  );
  const [switchConflicts, setSwitchConflicts] = useState<string[]>([]);

  function askToSwitch(item: SkillToggleTarget, conflicts: string[]) {
    setSwitchTarget(item);
    setSwitchConflicts(conflicts);
    switchModal.toggle(true);
  }

  async function setEnabled(
    item: SkillToggleTarget,
    enabled: boolean,
    replaceConflict = false
  ): Promise<void> {
    const holders = items.filter(
      (candidate) =>
        candidate.id !== item.id &&
        candidate.name === item.name &&
        candidate.enabled
    );
    if (enabled && !replaceConflict && holders.length > 0) {
      // A holder found here has the same name, so the dialog names nothing.
      askToSwitch(item, []);
      return;
    }
    const affected =
      enabled && replaceConflict
        ? items.filter(
            (candidate) =>
              candidate.id === item.id ||
              (candidate.name === item.name && candidate.enabled)
          )
        : [item];
    const affectedIds = new Set(affected.map(({ id }) => id));
    setPending((current) => new Set([...current, ...affectedIds]));
    setOptimistic((current) => {
      const next = new Map(current);
      if (enabled)
        affected.forEach((candidate) =>
          next.set(candidate.id, candidate.id === item.id)
        );
      else next.set(item.id, false);
      return next;
    });
    try {
      const updated = await setSkillEnabled(item.id, enabled, replaceConflict);
      if (replaceConflict) switchModal.toggle(false);
      if (enabled) onEnabled?.(updated);
      await refresh(
        (current) => {
          if (!current) return current;
          const apply = (skill: Skill): Skill =>
            skill.id === updated.id
              ? updated
              : enabled && skill.name === updated.name
                ? { ...skill, enabled: false }
                : skill;
          return {
            builtins: current.builtins.map(apply),
            customs: current.customs.map(apply),
          };
        },
        { revalidate: false }
      );
      void refreshSkillListsChecked(mutate, cache).then((ok) => {
        if (!ok)
          toast.error(t("page.toasts.refreshFailed", { name: item.name }));
      });
    } catch (error) {
      if (enabled && !replaceConflict && isSkillNameConflict(error)) {
        askToSwitch(item, skillNameConflictNames(error));
        return;
      }
      toast.error(
        describeError(
          error,
          t(
            enabled ? "page.toasts.enableFailed" : "page.toasts.disableFailed",
            { name: item.name }
          )
        )
      );
    } finally {
      setOptimistic((current) => {
        const next = new Map(current);
        affectedIds.forEach((id) => next.delete(id));
        return next;
      });
      setPending((current) => {
        const next = new Set(current);
        affectedIds.forEach((id) => next.delete(id));
        return next;
      });
    }
  }

  return {
    setEnabled,
    isPending: (id) => pending.has(id),
    enabledOf: (item) => optimistic.get(item.id) ?? item.enabled,
    switchTarget,
    switchConflicts,
    switchModal,
  };
}

/** Refreshes the skill lists after a change, and reports a failed refresh. */
export function useRefreshSkillLists(): () => void {
  const t = useTranslations("skills");
  const { mutate, cache } = useSWRConfig();
  return () => {
    void refreshSkillListsChecked(mutate, cache).then((ok) => {
      if (!ok) toast.error(t("page.toasts.listRefreshFailed"));
    });
  };
}
