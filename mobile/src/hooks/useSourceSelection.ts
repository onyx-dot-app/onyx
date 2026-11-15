import { useCallback, useMemo, useState } from "react";

import {
  applySourcePreferences,
  mergeSourcePreferences,
  parseSourcePreferences,
  type DocumentSource,
  type SourcePreferencesSnapshot,
} from "@/chat/sources";
import { appStorage } from "@/state/storage";
import { useSession } from "@/state/session";

// Per instance: a shared snapshot would carry another workspace's choices.
function storageKey(serverUrl: string): string {
  return `onyx.chat.source_preferences.${serverUrl}`;
}

/*
 * Storage is treated as best-effort on both sides. A read runs during render, so a throw there
 * would take the composer down; a write runs from the coupling state machine as well as from a
 * tap, so a throw there would escape an `onPress` handler into the global error handler. Losing
 * the saved choice is the smaller failure, and the log is what makes it diagnosable.
 */
function readSnapshot(
  serverUrl: string | null,
): SourcePreferencesSnapshot | null {
  if (serverUrl === null) return null;
  try {
    return parseSourcePreferences(appStorage.getString(storageKey(serverUrl)));
  } catch (error) {
    console.warn("Reading saved source preferences failed", error);
    return null;
  }
}

function writeSnapshot(
  serverUrl: string | null,
  snapshot: SourcePreferencesSnapshot,
): void {
  if (serverUrl === null) return;
  try {
    appStorage.set(storageKey(serverUrl), JSON.stringify(snapshot));
  } catch (error) {
    /*
     * Deliberately not rolled back: the selection is still the truth for this session, and
     * `commit` is driven by the search coupling too — snapping it back would desynchronise the
     * parked-source restore from the effect that reconciles search against it.
     */
    console.warn("Saving source preferences failed", error);
  }
}

const NO_SOURCES: DocumentSource[] = [];

export interface SourceSelection {
  selectedSources: DocumentSource[];
  /*
   * False until a catalogue has been reconciled with storage; before that an empty selection
   * means "not ready", not "every source off".
   */
  initialized: boolean;
  isSourceEnabled: (source: DocumentSource) => boolean;
  toggleSource: (source: DocumentSource) => void;
  setSources: (sources: DocumentSource[]) => void;
  enableAllSources: () => void;
  disableAllSources: () => void;
}

export function useSourceSelection(
  availableSources: DocumentSource[],
): SourceSelection {
  const serverUrl = useSession((state) => state.serverUrl);

  /*
   * Keyed by the catalogue, so a new one re-derives and drops sources the new agent can't reach.
   * Adjusted during render; an effect would publish stale state and cascade a second render.
   */
  const availableKey = availableSources.join(",");
  const [state, setState] = useState<{
    key: string;
    selected: DocumentSource[];
  }>({ key: "", selected: NO_SOURCES });

  const initialized = availableSources.length > 0 && state.key === availableKey;

  if (availableSources.length > 0 && state.key !== availableKey) {
    // Not written back: filling in defaults gives the same answer next launch.
    setState({
      key: availableKey,
      selected: mergeSourcePreferences(
        availableSources,
        readSnapshot(serverUrl),
      ),
    });
  }

  const selectedSources = initialized ? state.selected : NO_SOURCES;

  const commit = useCallback(
    (next: DocumentSource[]) => {
      setState({ key: availableKey, selected: next });
      writeSnapshot(
        serverUrl,
        applySourcePreferences(next, availableSources, readSnapshot(serverUrl)),
      );
    },
    [availableKey, availableSources, serverUrl],
  );

  const selectedSet = useMemo(
    () => new Set(selectedSources),
    [selectedSources],
  );

  const isSourceEnabled = useCallback(
    (source: DocumentSource) => selectedSet.has(source),
    [selectedSet],
  );

  const toggleSource = useCallback(
    (source: DocumentSource) => {
      if (!availableSources.includes(source)) return;
      commit(
        selectedSet.has(source)
          ? selectedSources.filter((candidate) => candidate !== source)
          : [...selectedSources, source],
      );
    },
    [availableSources, commit, selectedSet, selectedSources],
  );

  const setSources = useCallback(
    (sources: DocumentSource[]) => commit([...sources]),
    [commit],
  );

  const enableAllSources = useCallback(
    () => commit([...availableSources]),
    [availableSources, commit],
  );

  const disableAllSources = useCallback(() => commit(NO_SOURCES), [commit]);

  return {
    selectedSources,
    initialized,
    isSourceEnabled,
    toggleSource,
    setSources,
    enableAllSources,
    disableAllSources,
  };
}
