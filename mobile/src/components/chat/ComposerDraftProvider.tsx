import {
  createContext,
  useCallback,
  useMemo,
  useState,
  type ReactNode,
} from "react";

// The per-conversation composer draft (text + attachment refs into userFileStore). Synchronous UI
// state; mounted above the persistent ChatSurface so a draft survives navigation. Consumed only
// via `useComposerDraft`, so it can be promoted to a store later without touching components.
export interface DraftState {
  text: string;
  clientIds: string[];
}

export interface ComposerDraftValue {
  drafts: Record<string, DraftState>;
  setText: (draftKey: string, text: string) => void;
  addFiles: (draftKey: string, clientIds: string[]) => void;
  removeFile: (draftKey: string, id: string) => void;
  consume: (draftKey: string) => void; // accepted composer send: drop text + clientIds
  consumeAttachments: (draftKey: string) => void; // accepted starter send: drop clientIds, keep text
}

export const ComposerDraftContext = createContext<
  ComposerDraftValue | undefined
>(undefined);

const EMPTY_DRAFT: DraftState = { text: "", clientIds: [] };

export function ComposerDraftProvider({ children }: { children: ReactNode }) {
  const [drafts, setDrafts] = useState<Record<string, DraftState>>({});

  // Keeps the `clientIds` array reference stable across keystrokes (memoized chips skip a keystroke).
  const setText = useCallback((draftKey: string, text: string) => {
    setDrafts((prev) => {
      const current = prev[draftKey] ?? EMPTY_DRAFT;
      return { ...prev, [draftKey]: { ...current, text } };
    });
  }, []);

  const addFiles = useCallback((draftKey: string, clientIds: string[]) => {
    if (clientIds.length === 0) return;
    setDrafts((prev) => {
      const current = prev[draftKey] ?? EMPTY_DRAFT;
      const fresh = clientIds.filter((id) => !current.clientIds.includes(id));
      if (fresh.length === 0) return prev;
      return {
        ...prev,
        [draftKey]: { ...current, clientIds: [...current.clientIds, ...fresh] },
      };
    });
  }, []);

  const removeFile = useCallback((draftKey: string, id: string) => {
    setDrafts((prev) => {
      const current = prev[draftKey];
      if (!current || !current.clientIds.includes(id)) return prev;
      return {
        ...prev,
        [draftKey]: {
          ...current,
          clientIds: current.clientIds.filter((clientId) => clientId !== id),
        },
      };
    });
  }, []);

  const consume = useCallback((draftKey: string) => {
    setDrafts((prev) => {
      if (!prev[draftKey]) return prev;
      const next = { ...prev };
      delete next[draftKey];
      return next;
    });
  }, []);

  const consumeAttachments = useCallback((draftKey: string) => {
    setDrafts((prev) => {
      const current = prev[draftKey];
      if (!current || current.clientIds.length === 0) return prev;
      return { ...prev, [draftKey]: { ...current, clientIds: [] } };
    });
  }, []);

  const value = useMemo<ComposerDraftValue>(
    () => ({
      drafts,
      setText,
      addFiles,
      removeFile,
      consume,
      consumeAttachments,
    }),
    [drafts, setText, addFiles, removeFile, consume, consumeAttachments],
  );

  return (
    <ComposerDraftContext.Provider value={value}>
      {children}
    </ComposerDraftContext.Provider>
  );
}
