import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  jest,
} from "@jest/globals";
import { act, render, screen } from "@testing-library/react-native";
import { Fragment } from "react";

import { makeItem } from "@/chat/__tests__/fixtures";
import { StepContainer } from "@/components/chat/timeline/StepContainer";
import SvgCircle from "@/icons/circle";

import { ReasoningRenderer } from "../ReasoningRenderer";
import { RenderType, type RendererOutput } from "../timelineContract";

// StreamingMarkdown pulls a native markdown module; capture its props instead of rendering it.
let mockMarkdownProps: { content: string; isStreaming: boolean } | null = null;
jest.mock("@/components/chat/StreamingMarkdown", () => ({
  StreamingMarkdown: (props: { content: string; isStreaming: boolean }) => {
    mockMarkdownProps = props;
    return null;
  },
}));

// The StepContainer smoke test renders a Button, which navigates via expo-router's `router`.
jest.mock("expo-router", () => ({ router: { navigate: jest.fn() } }));

const reasoning = (text: string, status: "running" | "complete" = "running") =>
  makeItem({ kind: "reasoning", text, status });

function renderResults(results: RendererOutput) {
  return (
    <>
      {results.map((result, index) => (
        <Fragment key={index}>{result.content}</Fragment>
      ))}
    </>
  );
}

interface RenderOptions {
  items?: ReturnType<typeof makeItem>[];
  animate?: boolean;
  onComplete?: () => void;
  children?: (results: RendererOutput) => React.ReactElement;
}

function renderReasoning({
  items = [reasoning("thinking")],
  animate = true,
  onComplete = () => {},
  children = renderResults,
}: RenderOptions = {}) {
  return render(
    <ReasoningRenderer
      items={items}
      state={{ agent: null }}
      onComplete={onComplete}
      renderType={RenderType.FULL}
      animate={animate}
      stopPacketSeen={false}
    >
      {children}
    </ReasoningRenderer>,
  );
}

// Captures the emitted results *and* mounts their content, so `mockMarkdownProps` reflects the body.
function captureResults(items: ReturnType<typeof makeItem>[]) {
  let captured: RendererOutput | null = null;
  renderReasoning({
    items,
    children: (results) => {
      captured = results;
      return renderResults(results);
    },
  });
  return captured as unknown as RendererOutput;
}

describe("ReasoningRenderer", () => {
  beforeEach(() => {
    mockMarkdownProps = null;
  });

  it("renders the default status and no body before any reasoning arrives", () => {
    const results = captureResults([]);
    expect(results).toHaveLength(1);
    expect(results[0]!.status).toBe("Thinking");
    expect(results[0]!.icon).toBe(SvgCircle);
    expect(results[0]!.noPaddingRight).toBe(true);
    // The empty branch emits a fragment, so the markdown window never mounts.
    expect(mockMarkdownProps).toBeNull();
  });

  it("shows current reasoning under the default status", () => {
    renderReasoning({
      items: [reasoning("Let me go")],
    });
    expect(mockMarkdownProps?.content).toBe("Let me go");
    expect(mockMarkdownProps?.isStreaming).toBe(true);
  });

  it("promotes a leading markdown heading to the status and lifts it out of the body", () => {
    const results = captureResults([
      reasoning("## Reading the docs\n\nbody text"),
    ]);
    expect(results[0]!.status).toBe("Reading the docs");
    expect(mockMarkdownProps?.content).toBe("body text");
  });

  it("keeps plain prose in the body and falls back to the default status", () => {
    const results = captureResults([reasoning("Reading the docs")]);
    expect(results[0]!.status).toBe("Thinking");
    expect(mockMarkdownProps?.content).toBe("Reading the docs");
  });

  it("falls back to the default status when the heading extracts to an empty title", () => {
    // "# " is a syntactically valid heading whose text is empty; the status must not go blank.
    const results = captureResults([reasoning("# \n\nbody text")]);
    expect(results[0]!.status).toBe("Thinking");
  });

  it("stops streaming once the step is closed", () => {
    renderReasoning({
      items: [reasoning("done thinking", "complete")],
    });
    expect(mockMarkdownProps?.isStreaming).toBe(false);
  });

  it("does not expose a per-step collapse control (web parity)", () => {
    const results = captureResults([reasoning("thinking")]);
    expect(results[0]!.supportsCollapsible).toBeUndefined();
  });

  it("drops the right gutter on both the empty and populated branches", () => {
    expect(captureResults([])[0]!.noPaddingRight).toBe(true);
    expect(captureResults([reasoning("thinking")])[0]!.noPaddingRight).toBe(
      true,
    );
  });

  describe("saved reasoning", () => {
    it("renders a complete saved item", () => {
      renderReasoning({ items: [reasoning("recalled thinking", "complete")] });
      expect(mockMarkdownProps?.content).toBe("recalled thinking");
      expect(mockMarkdownProps?.isStreaming).toBe(false);
    });

    it("renders a complete empty item", () => {
      const results = captureResults([reasoning("", "complete")]);
      expect(results[0]!.status).toBe("Thinking");
      // hasEnd is true, so this is NOT the empty branch: an (empty) window still mounts.
      expect(mockMarkdownProps?.content).toBe("");
      expect(mockMarkdownProps?.isStreaming).toBe(false);
    });
  });

  describe("minimum thinking duration", () => {
    beforeEach(() => {
      jest.useFakeTimers();
    });
    afterEach(() => {
      jest.useRealTimers();
    });

    it("withholds completion for 500ms when reasoning ends immediately", () => {
      let calls = 0;
      renderReasoning({
        items: [reasoning("fast", "complete")],
        onComplete: () => {
          calls += 1;
        },
      });
      act(() => jest.advanceTimersByTime(499));
      expect(calls).toBe(0);
      act(() => jest.advanceTimersByTime(1));
      expect(calls).toBe(1);
    });

    it("completes immediately when reasoning already ran past the floor", () => {
      let calls = 0;
      const props = {
        state: { agent: null },
        onComplete: () => {
          calls += 1;
        },
        renderType: RenderType.FULL,
        animate: true,
        stopPacketSeen: false,
      } as const;
      const { rerender } = render(
        <ReasoningRenderer {...props} items={[reasoning("slow")]}>
          {renderResults}
        </ReasoningRenderer>,
      );
      act(() => jest.advanceTimersByTime(600));
      expect(calls).toBe(0);

      rerender(
        <ReasoningRenderer {...props} items={[reasoning("slow", "complete")]}>
          {renderResults}
        </ReasoningRenderer>,
      );
      expect(calls).toBe(1);
    });

    it("completes a saved item when animation is enabled", () => {
      let calls = 0;
      renderReasoning({
        items: [reasoning("recalled", "complete")],
        onComplete: () => {
          calls += 1;
        },
      });
      act(() => jest.advanceTimersByTime(500));
      expect(calls).toBe(1);
    });

    it("serves only the remainder of the floor when reasoning ran part of it", () => {
      // Pins `minimumThinkingDuration - elapsedTime`: 300ms elapsed leaves 200ms, not a fresh 500ms.
      let calls = 0;
      const props = {
        state: { agent: null },
        onComplete: () => {
          calls += 1;
        },
        renderType: RenderType.FULL,
        animate: true,
        stopPacketSeen: false,
      } as const;
      const { rerender } = render(
        <ReasoningRenderer {...props} items={[reasoning("mid")]}>
          {renderResults}
        </ReasoningRenderer>,
      );
      act(() => jest.advanceTimersByTime(300));
      rerender(
        <ReasoningRenderer {...props} items={[reasoning("mid", "complete")]}>
          {renderResults}
        </ReasoningRenderer>,
      );
      act(() => jest.advanceTimersByTime(199));
      expect(calls).toBe(0);
      act(() => jest.advanceTimersByTime(1));
      expect(calls).toBe(1);
    });

    it("skips the floor entirely for historical messages (animate=false)", () => {
      let calls = 0;
      renderReasoning({
        items: [reasoning("replayed", "complete")],
        animate: false,
        onComplete: () => {
          calls += 1;
        },
      });
      expect(calls).toBe(1);
    });

    it("completes once even as onComplete's identity churns across re-renders", () => {
      let calls = 0;
      const items = [reasoning("fast", "complete")];
      const props = {
        items,
        state: { agent: null },
        renderType: RenderType.FULL,
        animate: false,
        stopPacketSeen: false,
      } as const;
      const onComplete = () => {
        calls += 1;
      };
      const { rerender } = render(
        <ReasoningRenderer {...props} onComplete={onComplete}>
          {renderResults}
        </ReasoningRenderer>,
      );
      rerender(
        <ReasoningRenderer {...props} onComplete={() => calls++}>
          {renderResults}
        </ReasoningRenderer>,
      );
      rerender(
        <ReasoningRenderer {...props} onComplete={() => calls++}>
          {renderResults}
        </ReasoningRenderer>,
      );
      expect(calls).toBe(1);
    });

    it("does not complete after unmount", () => {
      let calls = 0;
      const { unmount } = renderReasoning({
        items: [reasoning("fast", "complete")],
        onComplete: () => {
          calls += 1;
        },
      });
      unmount();
      act(() => jest.advanceTimersByTime(1000));
      expect(calls).toBe(0);
    });
  });

  it("composes into a StepContainer with a header and no collapse control", () => {
    renderReasoning({
      items: [reasoning("## Planning\n\nthe body")],
      children: (results) => (
        <StepContainer
          stepIcon={results[0]!.icon ?? undefined}
          header={results[0]!.status}
          supportsCollapsible={results[0]!.supportsCollapsible}
          noPaddingRight={results[0]!.noPaddingRight}
          onToggle={() => {}}
        >
          {results[0]!.content}
        </StepContainer>
      ),
    });
    expect(screen.getByText("Planning")).toBeTruthy();
    expect(screen.UNSAFE_queryByType(SvgCircle)).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    expect(mockMarkdownProps?.content).toBe("the body");
  });
});
