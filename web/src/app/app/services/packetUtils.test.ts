import {
  getCitations,
  getTextContent,
  isStreamingComplete,
} from "@/app/app/services/packetUtils";
import {
  Packet,
  PacketIdentity,
  TextItem,
} from "@/app/app/services/streamingModels";

const identity: PacketIdentity = {
  response_id: 1,
  run_id: "root",
  message_id: "answer",
  part_id: "text",
};
const answer: TextItem = {
  kind: "text",
  text: "",
  purpose: "answer",
  status: "running",
  documents: [],
  citations: [],
};

it("reads the authoritative root answer without child text or duplicate deltas", () => {
  const packets: Packet[] = [
    {
      identity,
      obj: { type: "item_update", item: answer },
    },
    {
      identity,
      obj: {
        type: "item_delta",
        delta: { kind: "text", text: "draft", citations: [] },
      },
    },
    {
      identity: {
        ...identity,
        run_id: "child",
        message_id: "child-answer",
        parent_run_id: "root",
      },
      obj: { type: "item_update", item: { ...answer, text: "child" } },
    },
    {
      identity,
      obj: {
        type: "item_update",
        item: {
          ...answer,
          text: "Final",
          status: "complete",
          citations: [{ citation_number: 1, document_id: "doc" }],
        },
      },
    },
    { obj: { type: "stop" } },
  ];
  expect(getTextContent(packets)).toBe("Final");
  expect(getCitations(packets)).toEqual([
    { citation_num: 1, document_id: "doc" },
  ]);
  expect(isStreamingComplete(packets)).toBe(true);
});
