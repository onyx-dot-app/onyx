// What approval and question cards share: how a kind of card reads its requests from a response's
// packets, and where the cards sit among the response's display groups.
import { Packet } from "@/chat/streamingModels";

// How one kind of card reads its requests from a response's packets, and the statuses that this
// device learned before the server's resolution packets arrive.
export interface ToolCardSpec<Entry, Local, Card> {
  read: (packets: Packet[]) => Entry[];
  id: (entry: Entry) => string;
  // The server's resolution arrived.
  resolved: (entry: Entry) => boolean;
  useLocalStatuses: <U>(
    selector: (state: { localStatuses: ReadonlyMap<string, Local> }) => U,
  ) => U;
  forgetStatuses: (ids: string[]) => void;
  card: (entry: Entry, local: Local | undefined) => Card;
}

// A card (an approval request or a question) follows the display groups of its own turn and of
// every earlier turn; cards of one turn keep their order.
export function orderCardsByTurn<
  G extends { turn_index: number },
  C extends { turnIndex: number },
>(
  displayGroups: G[],
  cards: C[],
): ({ kind: "display"; group: G } | { kind: "card"; card: C })[] {
  const entries: (
    | { kind: "display"; turnIndex: number; group: G }
    | { kind: "card"; turnIndex: number; card: C }
  )[] = displayGroups.map((group) => ({
    kind: "display",
    turnIndex: group.turn_index,
    group,
  }));
  for (const card of cards) {
    const index = entries.findIndex(
      (entry) => entry.turnIndex > card.turnIndex,
    );
    entries.splice(index === -1 ? entries.length : index, 0, {
      kind: "card",
      turnIndex: card.turnIndex,
      card,
    });
  }
  return entries;
}
