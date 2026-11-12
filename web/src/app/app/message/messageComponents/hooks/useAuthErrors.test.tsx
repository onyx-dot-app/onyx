import { renderHook } from "@testing-library/react";
import { Packet, PacketType } from "@/app/app/services/streamingModels";
import { useAuthErrors } from "@/app/app/message/messageComponents/hooks/useAuthErrors";

function authError(toolName: string, toolId: number | null): Packet {
  return {
    placement: { turn_index: 0 },
    obj: {
      type: PacketType.CUSTOM_TOOL_DELTA,
      tool_name: toolName,
      tool_id: toolId,
      response_type: "text",
      error: {
        is_auth_error: true,
        is_unreachable: false,
        status_code: 401,
        message: "unauthorized",
      },
    },
  };
}

describe("useAuthErrors", () => {
  it("reports each tool without an ID once, keyed by its qualified name", () => {
    const packets = [
      authError("mcp__3__github__create_issue", null),
      authError("mcp__3__github__create_issue", null),
      authError("mcp__4__gitlab__create_issue", null),
    ];

    const { result } = renderHook(() => useAuthErrors(packets));

    expect(result.current).toEqual([
      { toolName: "create_issue", toolId: null },
      { toolName: "create_issue", toolId: null },
    ]);
  });

  it("reports each tool ID once", () => {
    const packets = [
      authError("custom__7__get_user", 7),
      authError("custom__7__get_user", 7),
    ];

    const { result } = renderHook(() => useAuthErrors(packets));

    expect(result.current).toEqual([{ toolName: "get_user", toolId: 7 }]);
  });
});
