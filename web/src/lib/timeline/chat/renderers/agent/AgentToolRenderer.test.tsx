import { render, screen } from "@tests/setup/test-utils";
import { toPlainString } from "@opal/components/text/InlineMarkdown";
import {
  type CustomToolPacket,
  CUSTOM_TOOL_ERROR_RESPONSE_TYPE,
  PacketType,
} from "@/app/app/services/streamingModels";
import { RenderType } from "@/lib/timeline/chat/message/messageComponents/types";
import { findRenderer } from "@/lib/timeline/chat/message/messageComponents/renderMessageComponent";
import CustomToolRenderer from "@/lib/timeline/chat/message/messageComponents/renderers/CustomToolRenderer";
import { STEP_ICONS } from "@/lib/timeline/icons";
import { AgentToolRenderer } from "@/lib/timeline/chat/renderers/agent/AgentToolRenderer";

const placement = { turn_index: 0, tab_index: 0 };
const prompt = "Wait idly for about one minute.\nThen write a limerick.";

type End = "running" | "done" | "error" | "toolError" | "rejected";

function call(
  toolName: string,
  args: Record<string, unknown> | null,
  end: End
): CustomToolPacket[] {
  const packets: CustomToolPacket[] = [
    {
      placement,
      obj: {
        type: PacketType.CUSTOM_TOOL_START,
        tool_name: toolName,
        display_name: "Start agent",
      },
    },
  ];
  if (args)
    packets.push({
      placement,
      obj: {
        type: PacketType.CUSTOM_TOOL_ARGS,
        tool_name: toolName,
        tool_args: args,
      },
    });
  if (end === "toolError")
    packets.push({
      placement,
      obj: {
        type: PacketType.CUSTOM_TOOL_DELTA,
        tool_name: toolName,
        response_type: "text",
        error: {
          is_auth_error: false,
          is_unreachable: false,
          status_code: 500,
          message: "Agent name exceeds 256 bytes.",
        },
      },
    });
  if (end === "rejected")
    packets.push({
      placement,
      obj: {
        type: PacketType.CUSTOM_TOOL_DELTA,
        tool_name: toolName,
        response_type: CUSTOM_TOOL_ERROR_RESPONSE_TYPE,
      },
    });
  if (end === "error")
    packets.push({ placement, obj: { type: PacketType.ERROR } });
  if (end !== "running")
    packets.push({ placement, obj: { type: PacketType.SECTION_END } });
  return packets;
}

function renderStep(packets: CustomToolPacket[]) {
  const onComplete = jest.fn();
  render(
    <AgentToolRenderer
      packets={packets}
      nestedCalls={[]}
      state={{}}
      onComplete={onComplete}
      renderType={RenderType.FULL}
      animate={false}
      stopPacketSeen={false}
    >
      {(results) => (
        <div>
          {results.map((result, index) => (
            <div key={index}>
              <span data-testid="icon">
                {String(result.icon === STEP_ICONS.agent)}
              </span>
              <span data-testid="status">
                {toPlainString(result.status ?? "")}
              </span>
              <span data-testid="done">
                {toPlainString(result.doneStatus ?? "")}
              </span>
              <div data-testid="body">{result.content}</div>
            </div>
          ))}
        </div>
      )}
    </AgentToolRenderer>
  );
  return onComplete;
}

const spawnArgs = { task_name: "limerick-6", message: prompt };

test.each([
  ["spawn_agent", spawnArgs],
  ["agent", { description: "limerick-6", prompt }],
  ["send_message", { target: "/root/limerick-6", message: "Hurry" }],
  ["interrupt_agent", { target: "/root/limerick-6" }],
])("routes %s to the agent step, not the generic tool step", (name, args) => {
  expect(findRenderer({ packets: call(name, args, "done") })).toBe(
    AgentToolRenderer
  );
});

test("list_agents keeps the generic tool step", () => {
  expect(findRenderer({ packets: call("list_agents", {}, "done") })).toBe(
    CustomToolRenderer
  );
});

test("a running spawn is its subagent card alone, with its prompt", () => {
  const onComplete = renderStep(call("spawn_agent", spawnArgs, "running"));
  // No step header: the card stands alone, as T3 Code's
  expect(screen.getByTestId("status")).toBeEmptyDOMElement();
  const body = screen.getByTestId("body");
  expect(body).toHaveTextContent("limerick-6");
  expect(body).toHaveTextContent(
    "Wait idly for about one minute. Then write a limerick."
  );
  expect(body).toHaveTextContent("Starting");
  expect(screen.queryByText("task_name:")).not.toBeInTheDocument();
  expect(onComplete).not.toHaveBeenCalled();
});

test.each([
  ["spawn_agent", spawnArgs],
  ["agent", { description: "limerick-6", prompt }],
])("a finished %s call is the agent's card", (name, args) => {
  const onComplete = renderStep(call(name, args, "done"));
  const body = screen.getByTestId("body");
  expect(body).toHaveTextContent("limerick-6");
  expect(body).toHaveTextContent("Then write a limerick.");
  expect(body).not.toHaveTextContent("Starting");
  expect(onComplete).toHaveBeenCalled();
});

test.each([
  [{ target: "/root/limerick-6", message: "Hurry" }],
  [{ to: "/root/limerick-6", message: "Hurry" }],
])(
  "a finished send_message call names the agent and shows the text sent",
  (args) => {
    const onComplete = renderStep(call("send_message", args, "done"));
    expect(screen.getByTestId("done")).toHaveTextContent(
      "Sent message to /root/limerick-6"
    );
    expect(screen.getByTestId("body").textContent).toBe("Hurry");
    expect(onComplete).toHaveBeenCalled();
  }
);

test("a finished interrupt names the agent and has no body", () => {
  renderStep(call("interrupt_agent", { target: "/root/limerick-6" }, "done"));
  expect(screen.getByTestId("done")).toHaveTextContent(
    "Interrupted /root/limerick-6"
  );
  expect(screen.getByTestId("body")).toBeEmptyDOMElement();
});

test.each(["error", "toolError", "rejected"] as const)(
  "a failed spawn (%s) says so on its card",
  (end) => {
    renderStep(call("spawn_agent", spawnArgs, end));
    expect(screen.getByTestId("body")).toHaveTextContent("Failed");
  }
);

test("a spawn without arguments names a subagent", () => {
  renderStep(call("spawn_agent", null, "running"));
  expect(screen.getByTestId("body")).toHaveTextContent("1 subagent");
});
