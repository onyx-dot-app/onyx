import { renderHook } from "@testing-library/react";
import { useAuthErrors } from "@/app/app/message/messageComponents/hooks/useAuthErrors";
import { usePacketProcessor } from "@/app/app/message/messageComponents/timeline/hooks/usePacketProcessor";
import {
  CustomToolResult,
  Packet,
  PacketIdentity,
  ToolItem,
} from "@/app/app/services/streamingModels";

const authenticationError: CustomToolResult = {
  type: "custom_tool_result",
  tool_name: "calendar",
  response_type: "json",
  tool_result: null,
  error: { is_auth_error: true, status_code: 401, message: "Connect calendar" },
};

function identity(call: string): PacketIdentity {
  return {
    response_id: 12,
    run_id: "root",
    message_id: "root:0",
    tool_call_id: call,
    part_id: "tool",
  };
}

function toolUpdate(call: string, overrides: Partial<ToolItem> = {}): Packet {
  return {
    identity: identity(call),
    obj: {
      type: "item_update",
      item: {
        kind: "tool",
        name: "calendar",
        tool_id: 7,
        arguments: {},
        output: "",
        metadata: null,
        status: "running",
        ...overrides,
      },
    },
  };
}

function useResponseAuthErrors(packets: Packet[]) {
  const { toolGroups } = usePacketProcessor(packets, 12);
  return useAuthErrors(toolGroups);
}

test("auth prompts follow deltas and authoritative replacements in the existing response view", () => {
  let packets = [toolUpdate("first")];
  const { result, rerender } = renderHook(
    ({ packets }) => useResponseAuthErrors(packets),
    { initialProps: { packets } }
  );
  expect(result.current).toEqual([]);

  packets = [
    ...packets,
    {
      identity: identity("first"),
      obj: {
        type: "item_delta",
        delta: { kind: "tool_output", metadata: authenticationError },
      },
    },
  ];
  rerender({ packets });
  expect(result.current).toEqual([{ toolName: "calendar", toolId: 7 }]);

  packets = [
    ...packets,
    toolUpdate("first", { status: "error", metadata: authenticationError }),
    toolUpdate("retry", { status: "error", metadata: authenticationError }),
  ];
  rerender({ packets });
  expect(result.current).toEqual([{ toolName: "calendar", toolId: 7 }]);

  const successfulResult: CustomToolResult = {
    ...authenticationError,
    error: null,
    tool_result: { events: [] },
  };
  packets = [
    ...packets,
    toolUpdate("first", { status: "complete", metadata: successfulResult }),
  ];
  rerender({ packets });
  // The other invocation still requires authentication.
  expect(result.current).toEqual([{ toolName: "calendar", toolId: 7 }]);
  packets = [
    ...packets,
    toolUpdate("retry", { status: "complete", metadata: successfulResult }),
  ];
  rerender({ packets });
  expect(result.current).toEqual([]);
});

test("deduplicates authentication failures by tool identity and excludes other errors", () => {
  const packets = [
    toolUpdate("first", { status: "error", metadata: authenticationError }),
    toolUpdate("same-id", {
      name: "calendar_alias",
      status: "error",
      metadata: authenticationError,
    }),
    toolUpdate("different-id", {
      tool_id: 8,
      status: "error",
      metadata: authenticationError,
    }),
    toolUpdate("no-id", {
      name: "mail",
      tool_id: null,
      status: "error",
      metadata: authenticationError,
    }),
    toolUpdate("same-name", {
      name: "mail",
      tool_id: null,
      status: "error",
      metadata: authenticationError,
    }),
    toolUpdate("normal-error", {
      tool_id: 9,
      status: "error",
      metadata: {
        ...authenticationError,
        error: {
          is_auth_error: false,
          status_code: 500,
          message: "Unavailable",
        },
      },
    }),
  ];
  const { result } = renderHook(() => useResponseAuthErrors(packets));
  expect(result.current).toEqual([
    { toolName: "calendar", toolId: 7 },
    { toolName: "calendar", toolId: 8 },
    { toolName: "mail", toolId: null },
  ]);
});
