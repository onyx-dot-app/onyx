/**
 * The tab rules that Craft's workspace panel and the chat's right panel
 * share: a tab opens at the end and becomes active, a closed tab hands the
 * active state to the most recently used open tab, tabs move by index, and a
 * few file viewers stay mounted.
 */

interface PanelTabsState<T> {
  tabs: T[];
  activeId: string | null;
  // Most recent first; only open tabs
  history: string[];
}

/** The history with `active` first, keeping only open tabs. */
export function panelTabHistory<T>(
  tabs: readonly T[],
  active: string | null,
  history: readonly string[],
  idOf: (tab: T) => string
): string[] {
  const openIds = new Set(tabs.map(idOf));
  return [...new Set(active ? [active, ...history] : history)].filter((id) =>
    openIds.has(id)
  );
}

/** Opens `target` at the end, unless it is open, and makes it active. */
export function openPanelTab<T>(
  state: Pick<PanelTabsState<T>, "tabs" | "history">,
  target: T,
  idOf: (tab: T) => string
): PanelTabsState<T> {
  const id = idOf(target);
  const tabs = state.tabs.some((tab) => idOf(tab) === id)
    ? state.tabs
    : [...state.tabs, target];
  return {
    tabs,
    activeId: id,
    history: panelTabHistory(tabs, id, state.history, idOf),
  };
}

/**
 * Closes a tab. When it was active, the most recently used tab becomes
 * active, else its neighbor, before it first.
 */
export function closePanelTab<T>(
  state: PanelTabsState<T>,
  id: string,
  idOf: (tab: T) => string
): PanelTabsState<T> {
  const index = state.tabs.findIndex((tab) => idOf(tab) === id);
  if (index < 0) return state;
  const tabs = state.tabs.filter((tab) => idOf(tab) !== id);
  const history = panelTabHistory(tabs, null, state.history, idOf);
  const neighbor = tabs[Math.max(0, index - 1)];
  const activeId =
    state.activeId === id
      ? (history[0] ?? (neighbor ? idOf(neighbor) : null))
      : state.activeId;
  return {
    tabs,
    activeId,
    history: panelTabHistory(tabs, activeId, history, idOf),
  };
}

/** Moves a tab to `index` among the other tabs. */
export function movePanelTab<T>(
  tabs: readonly T[],
  id: string,
  index: number,
  idOf: (tab: T) => string
): T[] {
  const tab = tabs.find((item) => idOf(item) === id);
  if (!tab) return [...tabs];
  const moved = tabs.filter((item) => idOf(item) !== id);
  moved.splice(Math.max(0, Math.min(moved.length, index)), 0, tab);
  return moved;
}

// An output panel keeps this many file viewers mounted, so switching back to
// a recent file tab does not load its file again
const MAX_RETAINED_FILE_VIEWERS = 5;

/** The file tabs whose viewers stay mounted, from file tab IDs by recent use. */
export function retainedFileViewers(recentFirst: readonly string[]): string[] {
  return [...new Set(recentFirst)].slice(0, MAX_RETAINED_FILE_VIEWERS);
}
