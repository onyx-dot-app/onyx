import { create } from "zustand";

interface ChatFindState {
  open: boolean;
  query: string;
  /** Bumped by each open, so an open bar focuses and selects its query again. */
  focusRequestId: number;
  /** Mounted `ChatFind`s: find opens only where a bar can show. */
  mounted: number;
}

const CLOSED: Omit<ChatFindState, "focusRequestId" | "mounted"> = {
  open: false,
  query: "",
};

export const useChatFindStore = create<ChatFindState>(() => ({
  ...CLOSED,
  focusRequestId: 0,
  mounted: 0,
}));

/** Opens find in the shown chat, or focuses it and selects its query. */
export function openChatFind(): void {
  useChatFindStore.setState((state) =>
    state.mounted === 0
      ? state
      : { open: true, focusRequestId: state.focusRequestId + 1 }
  );
}

/** Counts a mounted `ChatFind`; returns its unmount. */
export function mountChatFind(): () => void {
  useChatFindStore.setState((state) => ({ mounted: state.mounted + 1 }));
  return () =>
    useChatFindStore.setState((state) => ({ mounted: state.mounted - 1 }));
}

export function closeChatFind(): void {
  useChatFindStore.setState(CLOSED);
}

export function setChatFindQuery(query: string): void {
  useChatFindStore.setState({ query });
}
