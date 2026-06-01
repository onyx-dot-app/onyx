/* eslint-disable react-hooks/set-state-in-effect -- the init/re-init effects seed selected-source state from the MMKV snapshot (and reset it when the available-source set changes) by design; this is the lazy-initialization-from-an-external-store pattern. */
// Mirrors web useSourcePreferences, persisting per-source `uniqueKey` to MMKV
// (web used localStorage). New sources default enabled; stale keys drop on
// re-init; re-inits when the available set changes (e.g. agent switch).
//
// IMPORTANT: the web `toggleSource` removal branch has a bug
// (`filter(s => s.uniqueKey === key)` keeps only the toggled source). This port
// uses the CORRECTED `!==` removal.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { storage } from "@/state/persist";

import { getConfiguredSources, type MobileSource } from "./sourceMetadata";

const LS_KEY = "selectedInternalSearchSources";

interface SourcePreferencesSnapshot {
  sourcePreferences: Record<string, boolean>;
}

function loadSnapshot(): SourcePreferencesSnapshot | null {
  const saved = storage.getString(LS_KEY);
  if (!saved) return null;
  try {
    const res = JSON.parse(saved);
    if (
      typeof res !== "object" ||
      res === null ||
      typeof res.sourcePreferences !== "object" ||
      res.sourcePreferences === null ||
      Array.isArray(res.sourcePreferences)
    ) {
      return null;
    }
    for (const v of Object.values(res.sourcePreferences)) {
      if (typeof v !== "boolean") return null;
    }
    return res as SourcePreferencesSnapshot;
  } catch {
    return null;
  }
}

function persistSnapshot(enabled: MobileSource[], all: MobileSource[]) {
  const enabledKeys = new Set(enabled.map((s) => s.uniqueKey));
  const snapshot: SourcePreferencesSnapshot = {
    sourcePreferences: Object.fromEntries(
      all.map((s) => [s.uniqueKey, enabledKeys.has(s.uniqueKey)])
    ),
  };
  storage.set(LS_KEY, JSON.stringify(snapshot));
}

// Pure reader shared by the init effect and callers that need the freshest
// enabled set without mounting the hook (e.g. the send path — see useSendMessage).
// Reads MMKV fresh each call, so it is immune to cross-instance React staleness.
export function readEnabledSources(
  availableSourceStrings: string[]
): MobileSource[] {
  const configured = getConfiguredSources(availableSourceStrings);
  const saved = loadSnapshot();
  if (!saved) return configured; // first run: all enabled
  const has = (k: string) =>
    Object.prototype.hasOwnProperty.call(saved.sourcePreferences, k);
  const newSources = configured.filter((s) => !has(s.uniqueKey));
  const enabled = configured.filter(
    (s) => has(s.uniqueKey) && saved.sourcePreferences[s.uniqueKey]
  );
  return [...enabled, ...newSources]; // new sources enabled by default
}

export function useSourcePreferences(availableSourceStrings: string[]) {
  const configured = useMemo(
    () => getConfiguredSources(availableSourceStrings),
    [availableSourceStrings]
  );
  const [selected, setSelected] = useState<MobileSource[]>([]);
  const [initialized, setInitialized] = useState(false);

  // Re-init when the available source set changes (agent switch).
  const prevKey = useRef(availableSourceStrings.join(","));
  useEffect(() => {
    const key = availableSourceStrings.join(",");
    if (key !== prevKey.current) {
      prevKey.current = key;
      setInitialized(false);
    }
  }, [availableSourceStrings]);

  useEffect(() => {
    if (initialized || configured.length === 0) return;
    // Re-persist so dropped stale keys / new-source defaults are committed.
    const seeded = readEnabledSources(availableSourceStrings);
    setSelected(seeded);
    persistSnapshot(seeded, configured);
    setInitialized(true);
  }, [initialized, configured, availableSourceStrings]);

  const enableSources = useCallback(
    (sources: MobileSource[]) => {
      setSelected([...sources]);
      persistSnapshot(sources, configured);
    },
    [configured]
  );

  const enableAllSources = useCallback(
    () => enableSources(configured),
    [configured, enableSources]
  );

  const disableAllSources = useCallback(() => {
    setSelected([]);
    persistSnapshot([], configured);
  }, [configured]);

  const isSourceEnabled = useCallback(
    (uniqueKey: string) => selected.some((s) => s.uniqueKey === uniqueKey),
    [selected]
  );

  const toggleSource = useCallback(
    (uniqueKey: string) => {
      const src = configured.find((s) => s.uniqueKey === uniqueKey);
      if (!src) return;
      setSelected((prev) => {
        const isOn = prev.some((s) => s.uniqueKey === uniqueKey);
        const next = isOn
          ? prev.filter((s) => s.uniqueKey !== uniqueKey) // CORRECTED removal (web bug used ===)
          : [...prev, src];
        persistSnapshot(next, configured);
        return next;
      });
    },
    [configured]
  );

  return {
    configuredSources: configured,
    selectedSources: selected,
    sourcesInitialized: initialized,
    enableSources,
    enableAllSources,
    disableAllSources,
    toggleSource,
    isSourceEnabled,
  };
}
