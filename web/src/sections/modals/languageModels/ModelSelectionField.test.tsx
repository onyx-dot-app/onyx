/**
 * Component test: ModelSelectionField in auto-update mode.
 *
 * Regression coverage for the auto-mode model list:
 * - rows stay toggleable (admins can deselect models the config offers)
 * - a deselected row stays in the list so it can be re-selected before saving
 * - models the config offers but the admin hid are listed unchecked
 * - hidden models outside the offered set are not listed at all
 */

import { render, screen, setupUser } from "@tests/setup/test-utils";
import { PointerEventsCheckLevel } from "@testing-library/user-event";
import { Formik, Form } from "formik";
import { ModelSelectionField } from "@/sections/modals/languageModels/shared";
import { BaseLLMFormValues } from "@/sections/modals/languageModels/utils";
import { ModelConfiguration } from "@/lib/languageModels/types";
import { SWR_KEYS } from "@/lib/swr-keys";

const AUTO_CONFIG = {
  version: "1.5",
  updated_at: "2026-07-05T00:00:00Z",
  providers: {
    anthropic: {
      default_model: { name: "claude-opus-4-8" },
      additional_visible_models: [
        { name: "claude-opus-4-8", display_name: "Claude Opus 4.8" },
        { name: "claude-sonnet-4-6", display_name: "Claude Sonnet 4.6" },
        { name: "claude-haiku-4-5", display_name: "Claude Haiku 4.5" },
      ],
    },
  },
};

jest.mock("swr", () => {
  const actual = jest.requireActual("swr");
  return {
    ...actual,
    __esModule: true,
    useSWRConfig: () => ({ mutate: jest.fn() }),
    default: (key: string | null) => ({
      data: key === SWR_KEYS.llmAutoConfig ? AUTO_CONFIG : undefined,
      error: undefined,
      isLoading: false,
    }),
  };
});

function makeModel(name: string, isVisible: boolean): ModelConfiguration {
  return {
    name,
    is_visible: isVisible,
    max_input_tokens: null,
    supports_image_input: false,
    supports_reasoning: false,
    display_name: name,
    effectiveDisplayName: name,
  } as ModelConfiguration;
}

function renderField(models: ModelConfiguration[]) {
  const initialValues: BaseLLMFormValues = {
    provider: "anthropic",
    is_public: true,
    is_auto_mode: true,
    groups: [],
    personas: [],
    model_configurations: models,
  };

  let latestValues = initialValues;
  render(
    <Formik initialValues={initialValues} onSubmit={jest.fn()}>
      {(formik) => {
        latestValues = formik.values;
        return (
          <Form>
            <ModelSelectionField shouldShowAutoUpdateToggle={true} />
          </Form>
        );
      }}
    </Formik>
  );
  return () => latestValues;
}

function row(name: string): HTMLElement | null {
  return document.querySelector(`[data-model-name="${name}"]`);
}

describe("ModelSelectionField in auto mode", () => {
  test("lists offered models plus the visible off-config default, hides the rest", () => {
    renderField([
      // admin default, visible but NOT in the auto config
      makeModel("claude-sonnet-5", true),
      makeModel("claude-opus-4-8", true),
      // offered by the config but deselected by the admin earlier
      makeModel("claude-haiku-4-5", false),
      // hidden and outside the offered set — must not be listed
      makeModel("claude-3-opus", false),
    ]);

    expect(row("claude-sonnet-5")).not.toBeNull();
    expect(row("claude-opus-4-8")).not.toBeNull();
    expect(row("claude-haiku-4-5")).not.toBeNull();
    expect(row("claude-3-opus")).toBeNull();
  });

  test("deselecting an offered model updates form state and keeps the row listed", async () => {
    const user = setupUser({
      pointerEventsCheck: PointerEventsCheckLevel.Never,
    });
    const getValues = renderField([
      makeModel("claude-sonnet-5", true),
      makeModel("claude-opus-4-8", true),
    ]);

    const opusRow = row("claude-opus-4-8");
    expect(opusRow).not.toBeNull();
    await user.click(opusRow!.querySelector('[role="button"]')!);

    const opus = getValues().model_configurations.find(
      (m) => m.name === "claude-opus-4-8"
    );
    expect(opus?.is_visible).toBe(false);
    // still listed (it's in the offered set) so it can be re-selected
    expect(row("claude-opus-4-8")).not.toBeNull();
    // the other model is untouched
    expect(
      getValues().model_configurations.find((m) => m.name === "claude-sonnet-5")
        ?.is_visible
    ).toBe(true);
  });

  test("select all / deselect all operates on the offered set only", async () => {
    const user = setupUser({
      pointerEventsCheck: PointerEventsCheckLevel.Never,
    });
    const getValues = renderField([
      makeModel("claude-sonnet-5", true),
      makeModel("claude-opus-4-8", true),
      makeModel("claude-3-opus", false), // outside the offered set
    ]);

    await user.click(screen.getByRole("button", { name: "Deselect All" }));

    const values = getValues().model_configurations;
    expect(values.find((m) => m.name === "claude-opus-4-8")?.is_visible).toBe(
      false
    );
    expect(values.find((m) => m.name === "claude-sonnet-5")?.is_visible).toBe(
      false
    );
    // not offered, not shown — must not be flipped on by select-all cycles
    await user.click(screen.getByRole("button", { name: "Select All" }));
    expect(
      getValues().model_configurations.find((m) => m.name === "claude-3-opus")
        ?.is_visible
    ).toBe(false);
  });
});
