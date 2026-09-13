import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";
import { PortalHost } from "@rn-primitives/portal";

import { ModelList, ModelSelector } from "@/components/chat/ModelSelector";
import { Popover } from "@/components/ui/popover";
import type { ModelOption } from "@/chat/models";
import {
  ComposerToolsProvider,
  type ComposerTools,
} from "@/state/ComposerToolsProvider";
import { makeComposerTools } from "@/state/__tests__/fixtures";

// These reach MMKV, which jest can't load; the suite only needs the context the provider supplies.
jest.mock("@/state/storage");
jest.mock("@/api/settings", () => ({ useWorkspaceSettings: jest.fn() }));
jest.mock("@/hooks/useAgentPreferences", () => ({
  useAgentPreferences: jest.fn(),
}));
jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

function option(overrides: Partial<ModelOption> = {}): ModelOption {
  return {
    modelConfigurationId: 1,
    modelProvider: "OpenAI Prod",
    modelVersion: "gpt-5",
    providerDisplayName: "OpenAI Prod",
    displayName: "GPT-5",
    ...overrides,
  };
}

const gpt5 = option();
const claude = option({
  modelConfigurationId: 2,
  modelProvider: "Anthropic Prod",
  modelVersion: "claude-sonnet-5",
  providerDisplayName: "Anthropic Prod",
  displayName: "Claude Sonnet 5",
});

function renderSelector(overrides: Partial<ComposerTools> = {}) {
  const value: ComposerTools = makeComposerTools({
    modelOptions: [gpt5, claude],
    effectiveModel: gpt5,
    ...overrides,
  });
  render(
    // The popover renders through the portal host that app/_layout.tsx mounts at the root.
    <ComposerToolsProvider value={value}>
      <ModelSelector />
      <PortalHost />
    </ComposerToolsProvider>,
  );
  return value;
}

describe("ModelSelector", () => {
  it("labels the trigger with the active model", () => {
    renderSelector();
    expect(screen.getByText("GPT-5")).toBeTruthy();
  });

  it("renders nothing when there is nothing to choose between", () => {
    renderSelector({ modelOptions: [gpt5] });
    expect(screen.queryByText("GPT-5")).toBeNull();
  });

  it("keeps the list closed until the trigger is pressed", () => {
    renderSelector();
    expect(screen.queryByText("Claude Sonnet 5")).toBeNull();
  });

  it("falls back to a neutral label when no model has resolved yet", () => {
    renderSelector({ effectiveModel: null });
    expect(screen.getByText("Model")).toBeTruthy();
  });
});

/*
 * Exercised directly instead of through the trigger. The panel only mounts once the primitive
 * has measured the trigger, and the test renderer reports no layout for it to measure.
 */
describe("ModelList", () => {
  // The Popover root is here because each row dismisses the panel on press. It renders its
  // children whether or not the panel is open, so the list is still reachable.
  function renderList(options: ModelOption[] = [gpt5, claude]) {
    const onSelect = jest.fn();
    render(
      <Popover>
        <ModelList options={options} selected={gpt5} onSelect={onSelect} />
      </Popover>,
    );
    return onSelect;
  }

  it("lists every model", () => {
    renderList();
    expect(screen.getByText("GPT-5")).toBeTruthy();
    expect(screen.getByText("Claude Sonnet 5")).toBeTruthy();
  });

  it("reports the picked model", () => {
    const onSelect = renderList();
    fireEvent.press(screen.getByText("Claude Sonnet 5"));
    expect(onSelect).toHaveBeenCalledWith(claude);
  });

  it("groups by provider when more than one is offered", () => {
    renderList();
    expect(screen.getByText("OpenAI Prod")).toBeTruthy();
    expect(screen.getByText("Anthropic Prod")).toBeTruthy();
  });

  it("drops the headings when a single provider offers everything", () => {
    renderList([
      gpt5,
      { ...claude, providerDisplayName: gpt5.providerDisplayName },
    ]);
    expect(screen.queryByText("OpenAI Prod")).toBeNull();
  });
});
