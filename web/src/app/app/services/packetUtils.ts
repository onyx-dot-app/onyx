import {
  StreamingCitation,
  Packet,
  ResponseItem,
} from "@/app/app/services/streamingModels";
import { ResponseItems, textContent } from "@/app/app/services/responseItems";

export function isStreamingComplete(packets: Packet[]): boolean {
  return packets.some((packet) => packet.obj.type === "stop");
}

export function responseItems(packets: Packet[]): ResponseItem[] {
  const state = new ResponseItems();
  for (const packet of packets) state.apply(packet);
  return [...state.items.values()];
}

export function getTextContent(packets: Packet[]): string {
  return textContent(
    responseItems(packets).filter((item) => !item.identity.parent_run_id)
  );
}

export function getCitations(packets: Packet[]): StreamingCitation[] {
  const citations = responseItems(packets).flatMap((item) =>
    item.content.kind === "text" ? item.content.citations : []
  );
  return [
    ...new Map(
      citations.map((citation) => [
        citation.document_id,
        {
          citation_num: citation.citation_number,
          document_id: citation.document_id,
        },
      ])
    ).values(),
  ];
}
