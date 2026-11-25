import { render, screen } from "@tests/setup/test-utils";
import { toPlainString } from "@opal/components/text/InlineMarkdown";
import {
  type CustomToolPacket,
  PacketType,
} from "@/app/app/services/streamingModels";
import { RenderType } from "@/lib/timeline/chat/message/messageComponents/types";
import { findRenderer } from "@/lib/timeline/chat/message/messageComponents/renderMessageComponent";
import CustomToolRenderer from "@/lib/timeline/chat/message/messageComponents/renderers/CustomToolRenderer";
import { STEP_ICONS } from "@/lib/timeline/icons";
import { SkillToolRenderer } from "@/lib/timeline/chat/renderers/skill/SkillToolRenderer";

const placement = { turn_index: 0, tab_index: 0 };

type End = "running" | "done" | "error" | "toolError";

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
        display_name: "Read skill",
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
        response_type: "json",
        error: {
          is_auth_error: false,
          is_unreachable: false,
          status_code: 500,
          message: "Unknown skill",
        },
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
    <SkillToolRenderer
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
                {String(result.icon === STEP_ICONS.skill)}
              </span>
              <span data-testid="status">
                {toPlainString(result.status ?? "")}
              </span>
              <span data-testid="done">
                {toPlainString(result.doneStatus ?? "")}
              </span>
              <span data-testid="body">{String(result.content !== null)}</span>
            </div>
          ))}
        </div>
      )}
    </SkillToolRenderer>
  );
  return onComplete;
}

test.each([
  ["skills_read", { name: "pptx" }],
  ["skill", { skill: "pptx" }],
])(
  "routes %s to the skill step, not the generic tool step",
  (toolName, args) => {
    expect(findRenderer({ packets: call(toolName, args, "done") })).toBe(
      SkillToolRenderer
    );
  }
);

test("a custom tool keeps the generic tool step", () => {
  expect(findRenderer({ packets: call("get_meta_data", {}, "done") })).toBe(
    CustomToolRenderer
  );
});

test("a running read names the skill and is not complete", () => {
  const onComplete = renderStep(
    call("skills_read", { name: "pptx" }, "running")
  );
  expect(screen.getByTestId("icon")).toHaveTextContent("true");
  expect(screen.getByTestId("status")).toHaveTextContent("Reading skill pptx");
  expect(onComplete).not.toHaveBeenCalled();
});

test.each([
  ["skills_read", { name: "pptx" }, "Read skill pptx"],
  ["skill", { skill: "pptx" }, "Read skill pptx"],
  ["load_skill", { name: "pptx" }, "Loaded skill pptx"],
])(
  "a finished %s call names the skill and has no raw body",
  (toolName, args, title) => {
    const onComplete = renderStep(call(toolName, args, "done"));
    expect(screen.getByTestId("done")).toHaveTextContent(title);
    expect(screen.getByTestId("body")).toHaveTextContent("false");
    expect(onComplete).toHaveBeenCalled();
  }
);

test("a running load names the skill", () => {
  renderStep(call("load_skill", { name: "pptx" }, "running"));
  expect(screen.getByTestId("status")).toHaveTextContent("Loading skill pptx");
});

test.each([
  ["error", "skills_read", "Could not read skill pptx"],
  ["toolError", "load_skill", "Could not load skill pptx"],
] as const)("a failed call (%s) says so", (end, toolName, title) => {
  renderStep(call(toolName, { name: "pptx" }, end));
  expect(screen.getByTestId("done")).toHaveTextContent(title);
});

test("a call without a skill name falls back to the plain verb", () => {
  renderStep(call("load_skill", null, "done"));
  expect(screen.getByTestId("status")).toHaveTextContent(/^Loading skill$/);
  expect(screen.getByTestId("done")).toHaveTextContent(/^Loaded skill$/);
});
