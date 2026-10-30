import { useState } from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MultiModelSelector, {
  MAX_MODELS,
  type SelectedModel,
} from "@/sections/model-selector/MultiModelSelector";
import type { ReasoningManager } from "@/sections/model-selector/ModelSelectorContent";
import { llmOptionKey } from "@/lib/languageModels/options";
import type { LLMProviderDescriptor } from "@/lib/languageModels/types";
import { makeProvider } from "@tests/setup/llmProviderTestUtils";

// Stable across renders, so memoized option lists don't churn.
const mockT = (key: string, values?: Record<string, unknown>) =>
  values?.model ? `${key}:${values.model}` : key;
jest.mock("next-intl", () => ({ useTranslations: () => mockT }));
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({
    isLoading: false,
    multi_model_chat_enabled: true,
    reasoning_override_enabled: true,
    model_routing_enabled: false,
    hide_provider_grouping: false,
  }),
}));
jest.mock("@/lib/languageModels/hooks", () => ({
  useLanguageModelsForCurrentAgent: () => ({
    llmProviders: mockProviders,
    isLoading: false,
    modelPaging: undefined,
  }),
}));
const mockProviderNames = (entry: {
  productName: string;
  companyName: string;
}) => ({ productName: entry.productName, companyName: entry.companyName });
jest.mock("@/lib/languageModels/useProviderNames", () => ({
  useProviderNames: () => mockProviderNames,
}));
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: null }),
}));
// The real module pulls in provider modals through a circular import.
jest.mock("@/lib/languageModels/utils", () => ({
  getModelIcon: () =>
    function MockModelIcon() {
      return null;
    },
}));

const MODEL_NAMES = ["Model A", "Model B", "Model C", "Model D"];

const mockProviders: LLMProviderDescriptor[] = [
  makeProvider({
    id: 1,
    name: "Provider",
    provider: "openai",
    model_configurations: MODEL_NAMES.map((displayName, i) => ({
      id: i + 1,
      name: `model-${i + 1}`,
      is_visible: true,
      max_input_tokens: 128000,
      supports_image_input: false,
      supports_reasoning: true,
      effectiveDisplayName: displayName,
    })),
  }),
];

function selected(displayName: string): SelectedModel {
  const i = MODEL_NAMES.indexOf(displayName);
  return {
    name: "Provider",
    provider: "openai",
    modelName: `model-${i + 1}`,
    modelConfigurationId: i + 1,
    displayName,
  };
}

const reasoningManager: ReasoningManager = {
  reasoningEffort: null,
  updateReasoningEffort: jest.fn(),
};

/** Owns the selection and applies callbacks like useMultiModelChat. */
function Harness({
  initial,
  onRemove,
}: {
  initial: SelectedModel[];
  onRemove?: (index: number) => void;
}) {
  const [models, setModels] = useState(initial);
  return (
    <MultiModelSelector
      selectedModels={models}
      onAdd={(model) =>
        setModels((prev) =>
          prev.length >= MAX_MODELS ||
          prev.some((m) => llmOptionKey(m) === llmOptionKey(model))
            ? prev
            : [model, ...prev]
        )
      }
      onRemove={(index) => {
        onRemove?.(index);
        setModels((prev) => prev.filter((_, i) => i !== index));
      }}
      onReplace={(index, model) =>
        setModels((prev) => prev.map((m, i) => (i === index ? model : m)))
      }
      reasoningManager={reasoningManager}
    />
  );
}

// Row at x 600-900, y 700-740; every control inside it at its right end.
// Detached nodes measure 0x0 at the origin, as browsers report.
const ROW_RECT = new DOMRect(600, 700, 300, 40);
const CONTROL_RECT = new DOMRect(860, 704, 32, 32);

function mockLayout() {
  jest
    .spyOn(Element.prototype, "getBoundingClientRect")
    .mockImplementation(function (this: Element) {
      if (!this.isConnected) return new DOMRect(0, 0, 0, 0);
      if (this.getAttribute("data-testid") === "model-selector")
        return ROW_RECT;
      if (this.closest('[data-testid="model-selector"]')) return CONTROL_RECT;
      return new DOMRect(0, 0, 0, 0);
    });
  // jsdom reports a 0x0 viewport, which would clamp every position.
  Object.defineProperty(document.documentElement, "clientWidth", {
    configurable: true,
    value: 1280,
  });
  Object.defineProperty(document.documentElement, "clientHeight", {
    configurable: true,
    value: 800,
  });
}

function popperWrapper(): HTMLElement | null {
  return document.querySelector<HTMLElement>(
    "[data-radix-popper-content-wrapper]"
  );
}

/** The 0-width floating pane in jsdom puts `x` exactly on the anchor's right edge. */
function popperX(): number | null {
  const match = popperWrapper()?.style.transform.match(
    /translate\((-?[\d.]+)px/
  );
  return match ? Number(match[1]) : null;
}

/** autoUpdate re-measures on window resize; the setup ResizeObserver is a no-op. */
async function expectAnchoredToRow() {
  fireEvent(window, new Event("resize"));
  await waitFor(() => expect(popperX()).toBe(ROW_RECT.right));
}

function settingsButton(displayName: string): HTMLElement {
  return screen.getByRole("button", {
    name: `modelSettingsButton.ariaLabel:${displayName}`,
  });
}

describe("MultiModelSelector settings pane anchoring", () => {
  beforeEach(mockLayout);

  afterEach(() => {
    jest.restoreAllMocks();
    // Drop the own properties so the prototype getters apply again.
    Reflect.deleteProperty(document.documentElement, "clientWidth");
    Reflect.deleteProperty(document.documentElement, "clientHeight");
  });

  test("keeps the settings pane anchored to the selector row when adding the last model removes the add button", async () => {
    const user = userEvent.setup();
    render(<Harness initial={[selected("Model A"), selected("Model B")]} />);

    await user.click(
      screen.getByRole("button", { name: "multiModel.addModelButton.label" })
    );
    await waitFor(() => expect(popperX()).toBe(CONTROL_RECT.right));

    await user.click(settingsButton("Model C"));

    // The third model fills the last slot, so the add button is gone.
    expect(
      screen.queryByRole("button", { name: "multiModel.addModelButton.label" })
    ).toBeNull();
    expect(screen.getByRole("button", { name: "Model C" })).toBeInTheDocument();
    await expectAnchoredToRow();
  });

  test("keeps the settings pane anchored when replacing a pill from its settings button", async () => {
    const user = userEvent.setup();
    render(
      <Harness
        initial={[
          selected("Model A"),
          selected("Model B"),
          selected("Model C"),
        ]}
      />
    );

    await user.click(screen.getByRole("button", { name: "Model B" }));
    await waitFor(() => expect(popperX()).toBe(CONTROL_RECT.right));

    await user.click(settingsButton("Model D"));

    const row = screen.getByTestId("model-selector");
    expect(row).toHaveTextContent("Model D");
    expect(row).not.toHaveTextContent("Model B");
    await expectAnchoredToRow();
  });

  // Guards the remove path, where the anchor pill unmounts as the pane closes.
  test("removing the model whose settings pane is open closes the popover and calls onRemove", async () => {
    const user = userEvent.setup();
    const onRemove = jest.fn();
    render(
      <Harness
        initial={[
          selected("Model A"),
          selected("Model B"),
          selected("Model C"),
        ]}
        onRemove={onRemove}
      />
    );

    const pill = screen.getByRole("button", { name: "Model B" });
    await user.click(pill);
    await user.click(settingsButton("Model B"));
    expect(popperWrapper()).not.toBeNull();

    const removeIcon = Array.from(
      pill.querySelectorAll(".interactive-foreground-icon")
    ).at(-1);
    if (!removeIcon) throw new Error("remove icon not rendered");
    await user.click(removeIcon);

    expect(onRemove).toHaveBeenCalledWith(1);
    await waitFor(() => expect(popperWrapper()).toBeNull());
  });
});
