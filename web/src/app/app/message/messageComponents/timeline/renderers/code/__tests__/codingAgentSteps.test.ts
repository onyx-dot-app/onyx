import { buildAgentSteps } from "@/app/app/message/messageComponents/timeline/renderers/code/codingAgentSteps";
import {
  CodingAgentPacket,
  PacketType,
} from "@/app/app/services/streamingModels";

test("coding report is not repeated as a thinking step", () => {
  const native = (
    phase: "coding" | "report",
    content: string
  ): CodingAgentPacket => ({
    placement: { turn_index: 1, tab_index: 0, sub_turn_index: 1 },
    obj: {
      type: PacketType.PYDANTIC_AI,
      phase,
      event: {
        event_kind: "part_start",
        index: 0,
        part: { part_kind: "text", content },
      },
    },
  });
  const steps = buildAgentSteps([
    native("coding", "Inspecting the code"),
    native("report", "The result"),
    {
      placement: { turn_index: 1 },
      obj: { type: PacketType.CODING_AGENT_FINAL, answer: "The result" },
    },
  ]);
  expect(steps).toEqual([{ kind: "thinking", content: "Inspecting the code" }]);
});
