import { parsePacket } from "@/app/craft/utils/parsePacket";

describe("parsePacket", () => {
  it("parses raw opencode thought chunks that carry the event type in sessionUpdate", () => {
    expect(
      parsePacket({
        sessionUpdate: "agent_thought_chunk",
        content: { type: "text", text: "Inspecting the app state." },
      })
    ).toEqual({
      type: "thinking_chunk",
      text: "Inspecting the app state.",
    });
  });

  it("parses persisted agent thought packets as thinking chunks", () => {
    expect(
      parsePacket({
        type: "agent_thought",
        content: { type: "text", text: "Inspecting saved context." },
      })
    ).toEqual({
      type: "thinking_chunk",
      text: "Inspecting saved context.",
    });
  });
});
