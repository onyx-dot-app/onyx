import { render, screen } from "@tests/setup/test-utils";
import { toPlainString } from "@opal/components/text/InlineMarkdown";
import {
  SvgBrowserFile,
  SvgEarth,
  SvgKeyboard,
  SvgMousePointer,
} from "@opal/icons";
import {
  type CustomToolPacket,
  PacketType,
} from "@/app/app/services/streamingModels";
import { RenderType } from "@/lib/timeline/chat/message/messageComponents/types";
import { findRenderer } from "@/lib/timeline/chat/message/messageComponents/renderMessageComponent";
import { BrowserToolRenderer } from "@/lib/timeline/chat/renderers/sandbox/BrowserToolRenderer";
import CustomToolRenderer from "@/lib/timeline/chat/message/messageComponents/renderers/CustomToolRenderer";

const placement = { turn_index: 0, tab_index: 0 };

function packets(
  toolName: string,
  toolArgs: Record<string, unknown>,
  done: boolean
): CustomToolPacket[] {
  const start: CustomToolPacket[] = [
    {
      placement,
      obj: {
        type: PacketType.CUSTOM_TOOL_START,
        tool_name: toolName,
        display_name: "Open Page",
      },
    },
    {
      placement,
      obj: {
        type: PacketType.CUSTOM_TOOL_ARGS,
        tool_name: toolName,
        tool_args: toolArgs,
      },
    },
  ];
  return done
    ? [...start, { placement, obj: { type: PacketType.SECTION_END } }]
    : start;
}

function renderStatus(toolPackets: CustomToolPacket[]) {
  render(
    <BrowserToolRenderer
      packets={toolPackets}
      nestedCalls={[]}
      state={{}}
      onComplete={jest.fn()}
      renderType={RenderType.FULL}
      animate={false}
      stopPacketSeen={false}
    >
      {(results) => (
        <div>
          {results.map((result, index) => (
            <div key={index}>
              <span>{toPlainString(result.status ?? "")}</span>
              {result.content}
            </div>
          ))}
        </div>
      )}
    </BrowserToolRenderer>
  );
}

test("browser tool calls get the browser renderer, not the custom tool one", () => {
  const group = { packets: packets("browser_open", {}, false) };
  expect(findRenderer(group as never)).toBe(BrowserToolRenderer);
  const custom = { packets: packets("get_meta_data", {}, false) };
  expect(findRenderer(custom as never)).toBe(CustomToolRenderer);
});

test("opening a page names its host while running and when done", () => {
  renderStatus(
    packets("browser_open", { url: "https://example.com/docs" }, false)
  );
  expect(screen.getByText("Opening example.com")).toBeInTheDocument();
  expect(screen.getByText("https://example.com/docs")).toBeInTheDocument();
});

test("a done navigation and a page read say what they did", () => {
  renderStatus(packets("browser_navigate", { history: "back" }, true));
  expect(screen.getByText("Went back")).toBeInTheDocument();
  renderStatus(packets("browser_snapshot", {}, true));
  expect(screen.getByText("Read the page")).toBeInTheDocument();
});

test("a done call keeps its request and the page's response", () => {
  const toolPackets: CustomToolPacket[] = [
    ...packets("browser_act", { action: "click", ref: "e12" }, false),
    {
      placement,
      obj: {
        type: PacketType.CUSTOM_TOOL_DELTA,
        tool_name: "browser_act",
        response_type: "text",
        data: "Clicked the Sign in button",
      },
    },
    { placement, obj: { type: PacketType.SECTION_END } },
  ];
  renderStatus(toolPackets);
  expect(screen.getByText("Clicked an element")).toBeInTheDocument();
  expect(screen.getByText("click")).toBeInTheDocument();
  expect(screen.getByText("Clicked the Sign in button")).toBeInTheDocument();
});

test("typing and key presses name their text and key", () => {
  renderStatus(
    packets(
      "browser_act",
      { action: "type", ref: "e3", text: "onyx docs" },
      true
    )
  );
  expect(screen.getByText("Typed “onyx docs”")).toBeInTheDocument();
  renderStatus(
    packets("browser_act", { action: "press", key: "Enter" }, false)
  );
  expect(screen.getByText("Pressing Enter")).toBeInTheDocument();
});

test("each browser action gets its own icon", () => {
  const icons: Record<string, unknown> = {};
  const toolCalls: [string, string, Record<string, unknown>][] = [
    ["click", "browser_act", { action: "click", ref: "e1" }],
    ["scroll", "browser_act", { action: "scroll", delta_y: 400 }],
    ["type", "browser_act", { action: "type", text: "hi" }],
    ["upload", "browser_act", { action: "upload", paths: ["a.pdf"] }],
    ["open", "browser_open", { url: "https://onyx.app" }],
  ];
  for (const [label, toolName, args] of toolCalls) {
    render(
      <BrowserToolRenderer
        packets={packets(toolName, args, true)}
        nestedCalls={[]}
        state={{}}
        onComplete={jest.fn()}
        renderType={RenderType.FULL}
        animate={false}
        stopPacketSeen={false}
      >
        {(results) => {
          icons[label] = results[0]?.icon;
          return <></>;
        }}
      </BrowserToolRenderer>
    );
  }
  expect(icons.click).toBe(SvgMousePointer);
  expect(icons.scroll).toBe(SvgMousePointer);
  expect(icons.type).toBe(SvgKeyboard);
  expect(icons.upload).toBe(SvgBrowserFile);
  expect(icons.open).toBe(SvgEarth);
});
