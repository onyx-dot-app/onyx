import { create } from "zustand";

interface ChatFindState {
  open: boolean;
  query: string;
  /** Bumped by each open, so an open bar focuses and selects its query again. */
  focusRequestId: number;
}

const CLOSED: Omit<ChatFindState, "focusRequestId"> = {
  open: false,
  query: "",
};

export const useChatFindStore = create<ChatFindState>(() => ({
  ...CLOSED,
  focusRequestId: 0,
}));

/** Opens find in the shown chat, or focuses it and selects its query. */
export function openChatFind(): void {
  useChatFindStore.setState((state) => ({
    open: true,
    focusRequestId: state.focusRequestId + 1,
  }));
}

export function closeChatFind(): void {
  useChatFindStore.setState(CLOSED);
}

export function setChatFindQuery(query: string): void {
  useChatFindStore.setState({ query });
}
