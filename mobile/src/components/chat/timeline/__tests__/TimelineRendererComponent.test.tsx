import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import { act, render } from "@testing-library/react-native";
import type { Mock } from "jest-mock";
import type { ComponentProps } from "react";

import { findRenderer } from "@/components/chat/renderers/findRenderer";
import {
  RenderType,
  type DispatchRenderer,
  type TimelineRendererResult,
} from "@/components/chat/renderers/timelineContract";
import { TimelineRendererComponent } from "@/components/chat/timeline/TimelineRendererComponent";
import type { Packet } from "@/chat/streamingModels";

jest.mock("@/components/chat/renderers/findRenderer", () => ({
  findRenderer: jest.fn(),
}));

const mockFindRenderer = findRenderer as unknown as Mock<
  (packets: Packet[]) => DispatchRenderer | null
>;

// Stub renderer emitting one result. The RenderType it received surfaces as the enhanced result's
// `renderType` (the component derives one value for both), so no render-time capture is needed.
const MockRenderer: DispatchRenderer = (props) =>
  props.children([
    {
      icon: null,
      status: "S",
      content: <></>,
      supportsCollapsible: true,
      timelineLayout: "content",
    },
  ]);

// Omits the optional timelineLayout so enhanceResult's `?? "timeline"` default is exercised.
const MockRendererNoLayout: DispatchRenderer = (props) =>
  props.children([{ icon: null, status: "S", content: <></> }]);

function renderTimeline(
  extraProps: Partial<ComponentProps<typeof TimelineRendererComponent>> = {},
) {
  let captured: TimelineRendererResult[] | null = null;
  render(
    <TimelineRendererComponent
      packets={[]}
      chatState={{ agent: null }}
      animate={false}
      stopPacketSeen={false}
      {...extraProps}
    >
      {(results) => {
        captured = results;
        return <></>;
      }}
    </TimelineRendererComponent>,
  );
  return () => captured!;
}

describe("TimelineRendererComponent", () => {
  beforeEach(() => {
    mockFindRenderer.mockReturnValue(MockRenderer);
  });

  it("derives FULL when expanded and COMPACT when collapsed", () => {
    expect(renderTimeline({ defaultExpanded: true })()[0].renderType).toBe(
      RenderType.FULL,
    );
    expect(renderTimeline({ defaultExpanded: false })()[0].renderType).toBe(
      RenderType.COMPACT,
    );
  });

  it("honors renderTypeOverride regardless of expand state", () => {
    const results = renderTimeline({
      defaultExpanded: false,
      renderTypeOverride: RenderType.FULL,
    })();
    expect(results[0].renderType).toBe(RenderType.FULL);
  });

  it("enhances each result with the collapse/timeline fields", () => {
    const results = renderTimeline({
      defaultExpanded: true,
      isLastStep: false,
    })();
    expect(results).toHaveLength(1);
    const [result] = results;
    expect(result.status).toBe("S");
    expect(result.isExpanded).toBe(true);
    expect(result.renderType).toBe(RenderType.FULL);
    expect(result.isLastStep).toBe(false);
    expect(result.timelineLayout).toBe("content");
    expect(typeof result.onToggle).toBe("function");
  });

  it("toggles expand state, flipping the derived render type", () => {
    const get = renderTimeline({ defaultExpanded: true });
    expect(get()[0].renderType).toBe(RenderType.FULL);
    act(() => {
      get()[0].onToggle();
    });
    expect(get()[0].renderType).toBe(RenderType.COMPACT);
  });

  it("defaults timelineLayout to 'timeline' and isLastStep to true when both are unset", () => {
    mockFindRenderer.mockReturnValue(MockRendererNoLayout);
    // renderTimeline omits isLastStep → the `?? true` default runs.
    const [result] = renderTimeline({ defaultExpanded: true })();
    expect(result.timelineLayout).toBe("timeline");
    expect(result.isLastStep).toBe(true);
  });

  it("hands an empty result to children when no renderer matches", () => {
    mockFindRenderer.mockReturnValue(null);
    const results = renderTimeline({
      defaultExpanded: true,
      isLastStep: true,
    })();
    expect(results).toHaveLength(1);
    const [result] = results;
    expect(result.icon).toBeNull();
    expect(result.status).toBeNull();
    expect(result.supportsCollapsible).toBe(false);
    expect(result.timelineLayout).toBe("timeline");
    expect(result.isExpanded).toBe(true);
    expect(result.renderType).toBe(RenderType.FULL);
    expect(result.isLastStep).toBe(true);
  });
});
