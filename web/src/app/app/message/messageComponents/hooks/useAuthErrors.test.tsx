import { renderHook } from "@testing-library/react";
import { Packet, PacketType } from "@/app/app/services/streamingModels";
import { useAuthErrors } from "@/app/app/message/messageComponents/hooks/useAuthErrors";

function authError(
  turnIndex: number,
  toolName: string,
  displayName: string,
  toolId: number | null
): Packet[] {
  const placement = { turn_index: turnIndex, tab_index: 0 };
  return [
    {
      placement,
      obj: {
        type: PacketType.CUSTOM_TOOL_START,
        tool_name: toolName,
        display_name: displayName,
        tool_id: toolId,
      },
    },
    {
      placement,
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
    },
  ];
}

describe("useAuthErrors", () => {
  it("reports each tool without an ID once, keyed by its qualified name", () => {
    const packets = [
      ...authError(0, "mcp__3__github__create_issue", "Create issue", null),
      ...authError(1, "mcp__3__github__create_issue", "Create issue", null),
      ...authError(2, "mcp__4__gitlab__create_issue", "New issue", null),
    ];

    const { result } = renderHook(() => useAuthErrors(packets));

    expect(result.current).toEqual([
      { turnIndex: 0, toolName: "Create issue", toolId: null },
      { turnIndex: 2, toolName: "New issue", toolId: null },
    ]);
  });

  it("reports each tool ID once", () => {
    const packets = [
      ...authError(0, "custom__7__get_user", "Get user", 7),
      ...authError(1, "custom__7__get_user", "Get user", 7),
    ];

    const { result } = renderHook(() => useAuthErrors(packets));

    expect(result.current).toEqual([
      { turnIndex: 0, toolName: "Get user", toolId: 7 },
    ]);
  });

  it("reports a tool again after an accepted user message", () => {
    const packets: Packet[] = [
      ...authError(0, "custom__7__get_user", "Get user", 7),
      {
        placement: { turn_index: 1 },
        obj: {
          type: PacketType.USER_MESSAGE,
          id: "accepted",
          message: "Try again",
        },
      },
      ...authError(2, "custom__7__get_user", "Get user", 7),
      ...authError(2, "custom__7__get_user", "Get user", 7),
    ];

    const { result } = renderHook(() => useAuthErrors(packets));

    expect(result.current).toEqual([
      { turnIndex: 0, toolName: "Get user", toolId: 7 },
      { turnIndex: 2, toolName: "Get user", toolId: 7 },
    ]);
  });

  it("reports errors appended to the same packet array", () => {
    const packets: Packet[] = [authError("custom__7__get_user", "get_user", 7)];
    const { result, rerender } = renderHook(() => useAuthErrors(packets));
    expect(result.current).toHaveLength(1);

    // Streams append to the array they already passed.
    packets.push(
      {
        placement: { turn_index: 1 },
        obj: {
          type: PacketType.USER_MESSAGE,
          id: "accepted",
          message: "Try again",
        },
      },
      authError("custom__7__get_user", "get_user", 7, 2)
    );
    rerender();

    expect(result.current).toEqual([
      { turnIndex: 0, toolName: "get_user", toolId: 7 },
      { turnIndex: 2, toolName: "get_user", toolId: 7 },
    ]);
  });
});
