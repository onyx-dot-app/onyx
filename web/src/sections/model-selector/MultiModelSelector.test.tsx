import { useState } from "react";
import {
  act,
  render,
  screen,
  waitFor,
  fireEvent,
  within,
} from "@testing-library/react";
import { setupUser } from "@tests/setup/test-utils";
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

const DEFAULT_SETTINGS = {
  isLoading: false,
  multi_model_chat_enabled: true,
  reasoning_override_enabled: true,
  model_routing_enabled: false,
  hide_provider_grouping: false,
};
// Reset per test so a case can flip a workspace flag.
let mockSettings = { ...DEFAULT_SETTINGS };
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => mockSettings,
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
// The real module pulls in provider modals through a circular import. The
// empty icon also leaves the pill's x as its only svg.
jest.mock("@/lib/languageModels/utils", () => ({
  getModelIcon: () =>
    function MockModelIcon() {
      return null;
    },
}));

interface ModelFixture {
  provider: { id: number; name: string; provider: string };
  modelName: string;
  configId: number;
}

const PROVIDER = { id: 1, name: "Provider", provider: "openai" };
// A second provider makes the list render collapsible provider groups.
const OTHER_PROVIDER = { id: 2, name: "Provider Two", provider: "anthropic" };

const MODELS: Record<string, ModelFixture> = {
  "Model A": { provider: PROVIDER, modelName: "model-1", configId: 1 },
  "Model B": { provider: PROVIDER, modelName: "model-2", configId: 2 },
  "Model C": { provider: PROVIDER, modelName: "model-3", configId: 3 },
  "Model D": { provider: PROVIDER, modelName: "model-4", configId: 4 },
  "Model E": { provider: OTHER_PROVIDER, modelName: "model-5", configId: 5 },
  "Model F": { provider: OTHER_PROVIDER, modelName: "model-6", configId: 6 },
};

const mockProviders: LLMProviderDescriptor[] = [PROVIDER, OTHER_PROVIDER].map(
  (provider) =>
    makeProvider({
      ...provider,
      provider_display_name: provider.name,
      model_configurations: Object.entries(MODELS)
        .filter(([, model]) => model.provider === provider)
        .map(([displayName, model]) => ({
          id: model.configId,
          name: model.modelName,
          is_visible: true,
          max_input_tokens: 128000,
          supports_image_input: false,
          supports_reasoning: true,
          effectiveDisplayName: displayName,
        })),
    })
);

function selected(displayName: string): SelectedModel {
  const model = MODELS[displayName];
  if (!model) throw new Error(`unknown model ${displayName}`);
  return {
    name: model.provider.name,
    provider: model.provider.provider,
    modelName: model.modelName,
    modelConfigurationId: model.configId,
    displayName,
  };
}

const reasoningManager: ReasoningManager = {
  reasoningEffort: null,
  updateReasoningEffort: jest.fn(),
};

interface Callbacks {
  onAdd: jest.Mock;
  onRemove: jest.Mock;
  onReplace: jest.Mock;
}

function makeCallbacks(): Callbacks {
  return { onAdd: jest.fn(), onRemove: jest.fn(), onReplace: jest.fn() };
}

/** Owns the selection and applies callbacks like useMultiModelChat. */
function Harness({
  initial,
  callbacks,
}: {
  initial: SelectedModel[];
  callbacks?: Callbacks;
}) {
  const [models, setModels] = useState(initial);
  return (
    <MultiModelSelector
      selectedModels={models}
      onAdd={(model) => {
        callbacks?.onAdd(model);
        setModels((prev) =>
          prev.length >= MAX_MODELS ||
          prev.some((m) => llmOptionKey(m) === llmOptionKey(model))
            ? prev
            : [model, ...prev]
        );
      }}
      onRemove={(index) => {
        callbacks?.onRemove(index);
        setModels((prev) => prev.filter((_, i) => i !== index));
      }}
      onReplace={(index, model) => {
        callbacks?.onReplace(index, model);
        setModels((prev) => prev.map((m, i) => (i === index ? model : m)));
      }}
      reasoningManager={reasoningManager}
    />
  );
}

function renderPicker(names: string[], callbacks?: Callbacks) {
  return render(
    <Harness initial={names.map(selected)} callbacks={callbacks} />
  );
}

// ---------------------------------------------------------------------------
// Layout and popper position
// ---------------------------------------------------------------------------

const ROW = "row";
const ADD = "add";
const ADD_LABEL = "multiModel.addModelButton.label";
/** Opal Popover.Content's default sideOffset. */
const SIDE_OFFSET = 4;

// Every element the popover can measure has its own rect, so a position names
// its anchor. Keys are ROW, ADD or a pill's display name.
function defaultRects(): Map<string, DOMRect> {
  return new Map([
    [ROW, new DOMRect(300, 700, 600, 40)],
    [ADD, new DOMRect(320, 704, 32, 32)],
    ["Model A", new DOMRect(800, 704, 90, 32)],
    ["Model B", new DOMRect(700, 704, 90, 32)],
    ["Model C", new DOMRect(600, 704, 90, 32)],
    ["Model D", new DOMRect(500, 704, 90, 32)],
    ["Model E", new DOMRect(400, 704, 90, 32)],
    ["Model F", new DOMRect(360, 704, 30, 32)],
  ]);
}
let mockRects: Map<string, DOMRect> = defaultRects();

function rectKey(element: Element): string | null {
  if (element.getAttribute("data-testid") === "model-selector") return ROW;
  if (
    element.tagName !== "BUTTON" ||
    !element.closest('[data-testid="model-selector"]')
  )
    return null;
  if (element.getAttribute("aria-label") === ADD_LABEL) return ADD;
  return element.textContent;
}

function rectOf(key: string): DOMRect {
  const rect = mockRects.get(key);
  if (!rect) throw new Error(`no rect for ${key}`);
  return rect;
}

/** Moves an element, as a layout shift would; autoUpdate sees it on the next resize. */
function setRect(key: string, rect: DOMRect) {
  mockRects.set(key, rect);
}

function mockLayout() {
  mockRects = defaultRects();
  jest
    .spyOn(Element.prototype, "getBoundingClientRect")
    .mockImplementation(function (this: Element) {
      if (!this.isConnected) return new DOMRect(0, 0, 0, 0);
      const key = rectKey(this);
      return (key && mockRects.get(key)) || new DOMRect(0, 0, 0, 0);
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

function openPopper(): HTMLElement {
  const wrapper = popperWrapper();
  if (!wrapper) throw new Error("picker menu is not open");
  return wrapper;
}

function popperXY(): { x: number; y: number } | null {
  const match = popperWrapper()?.style.transform.match(
    /translate\((-?[\d.]+)px, (-?[\d.]+)px\)/
  );
  return match ? { x: Number(match[1]), y: Number(match[2]) } : null;
}

/**
 * The 0x0 jsdom pane sits with its right edge on the anchor's right and its
 * bottom SIDE_OFFSET above the anchor's top. autoUpdate re-measures on window
 * resize; the setup ResizeObserver and IntersectionObserver are no-ops.
 */
async function expectAnchoredAt(key: string) {
  const rect = rectOf(key);
  fireEvent(window, new Event("resize"));
  await waitFor(() =>
    expect(popperXY()).toEqual({
      x: rect.right,
      y: rect.top - SIDE_OFFSET,
    })
  );
}

// ---------------------------------------------------------------------------
// Row, pill and pane queries
// ---------------------------------------------------------------------------

type User = ReturnType<typeof setupUser>;

function selectorRow(): HTMLElement {
  return screen.getByTestId("model-selector");
}

function addButton(): HTMLElement | null {
  return within(selectorRow()).queryByRole("button", { name: ADD_LABEL });
}

function pill(displayName: string): HTMLElement {
  return within(selectorRow()).getByRole("button", { name: displayName });
}

function pillNames(): string[] {
  return within(selectorRow())
    .getAllByRole("button")
    .filter((button) => button !== addButton())
    .map((button) => button.textContent ?? "");
}

/** The pill's trailing x, the only svg in a pill since provider icons are mocked empty. */
function pillX(pillElement: HTMLElement): Element | null {
  return (
    Array.from(
      pillElement.querySelectorAll(".interactive-foreground-icon")
    ).find((icon) => icon.querySelector("svg")) ?? null
  );
}

async function clickPillX(user: User, displayName: string) {
  const x = pillX(pill(displayName));
  if (!x) throw new Error(`pill ${displayName} has no x`);
  await user.click(x);
}

function rowName(displayName: string): RegExp {
  return new RegExp(`^${displayName}\\s*${MODELS[displayName]?.modelName}$`);
}

/** A list row; rows in a collapsed provider group are aria-hidden and not found. */
function queryRow(displayName: string): HTMLElement | null {
  return within(openPopper()).queryByRole("button", {
    name: rowName(displayName),
  });
}

function row(displayName: string): HTMLElement {
  const found = queryRow(displayName);
  if (!found) throw new Error(`row ${displayName} is not shown`);
  return found;
}

/** Opal `Disabled` wraps each row in a fieldset that it disables. */
function rowFieldset(displayName: string): HTMLElement {
  const fieldset = row(displayName).closest("fieldset");
  if (!fieldset) throw new Error(`row ${displayName} has no Disabled wrapper`);
  return fieldset;
}

function expectRowSelected(displayName: string, isSelected: boolean) {
  expect(row(displayName)).toHaveAttribute(
    "data-interactive-state",
    isSelected ? "selected" : "empty"
  );
}

function settingsButton(displayName: string): HTMLElement {
  return within(openPopper()).getByRole("button", {
    name: `modelSettingsButton.ariaLabel:${displayName}`,
  });
}

function groupHeader(displayName: string): HTMLElement {
  return within(openPopper()).getByText(displayName, { exact: true });
}

function searchInput(): HTMLElement | null {
  return within(openPopper()).queryByPlaceholderText("searchInput.placeholder");
}

function expectList() {
  expect(searchInput()).not.toBeNull();
}

/** The pane header names the model and its model id, and the list's search is gone. */
function expectPane(displayName: string) {
  const popper = openPopper();
  expect(searchInput()).toBeNull();
  expect(within(popper).getByText(displayName)).toBeInTheDocument();
  expect(
    within(popper).getByText(MODELS[displayName]?.modelName ?? "")
  ).toBeInTheDocument();
}

/** The pane's back arrow is its first (icon-only) button. */
async function clickBack(user: User) {
  const back = within(openPopper()).getAllByRole("button")[0];
  if (!back) throw new Error("pane has no back button");
  await user.click(back);
}

async function openFromAdd(user: User) {
  const add = addButton();
  if (!add) throw new Error("add button is hidden");
  await user.click(add);
  await waitFor(() => expect(popperWrapper()).not.toBeNull());
}

async function openFromPill(user: User, displayName: string) {
  await user.click(pill(displayName));
  await waitFor(() => expect(popperWrapper()).not.toBeNull());
}

async function typeSearch(user: User, text: string) {
  const search = searchInput();
  if (!search) throw new Error("list has no search input");
  await user.type(search, text);
}

function expectNoCallbacks(callbacks: Callbacks) {
  expect(callbacks.onAdd).not.toHaveBeenCalled();
  expect(callbacks.onRemove).not.toHaveBeenCalled();
  expect(callbacks.onReplace).not.toHaveBeenCalled();
}

describe("MultiModelSelector", () => {
  beforeEach(() => {
    mockSettings = { ...DEFAULT_SETTINGS };
    mockLayout();
  });

  afterEach(() => {
    jest.restoreAllMocks();
    // Drop the own properties so the prototype getters apply again.
    Reflect.deleteProperty(document.documentElement, "clientWidth");
    Reflect.deleteProperty(document.documentElement, "clientHeight");
  });

  // -------------------------------------------------------------------------
  // Anchoring
  // -------------------------------------------------------------------------

  describe("anchoring", () => {
    test("the list sits on + and follows it through row adds and removes, and on the row while + is hidden", async () => {
      const user = setupUser();
      renderPicker(["Model A"]);

      await openFromAdd(user);
      expectList();
      await expectAnchoredAt(ADD);

      await user.click(row("Model B"));
      expect(pillNames()).toEqual(["Model B", "Model A"]);
      setRect(ADD, new DOMRect(220, 704, 32, 32));
      await expectAnchoredAt(ADD);

      await user.click(row("Model B"));
      expect(pillNames()).toEqual(["Model A"]);
      setRect(ADD, new DOMRect(320, 704, 32, 32));
      await expectAnchoredAt(ADD);

      await user.click(row("Model B"));
      await user.click(row("Model C"));
      expect(pillNames()).toEqual(["Model C", "Model B", "Model A"]);
      expect(addButton()).toBeNull();
      await expectAnchoredAt(ROW);

      await clickPillX(user, "Model C");
      expect(pillNames()).toEqual(["Model B", "Model A"]);
      expectList();
      await expectAnchoredAt(ADD);
    });

    test("a pill opens its pane on that pill, and the pane follows the pill when it moves", async () => {
      const user = setupUser();
      renderPicker(["Model A", "Model B"]);

      await openFromPill(user, "Model B");
      expectPane("Model B");
      await expectAnchoredAt("Model B");

      setRect("Model B", new DOMRect(760, 704, 90, 32));
      await expectAnchoredAt("Model B");

      await user.click(pill("Model A"));
      expectPane("Model A");
      await expectAnchoredAt("Model A");
    });

    test("settings on a selected row moves the menu to that pill, back returns it to +", async () => {
      const user = setupUser();
      renderPicker(["Model A", "Model B"]);

      await openFromAdd(user);
      await expectAnchoredAt(ADD);

      await user.click(settingsButton("Model B"));
      expectPane("Model B");
      await expectAnchoredAt("Model B");

      await clickBack(user);
      expectList();
      await expectAnchoredAt(ADD);
    });

    test("the pane of an unselected model sits on +", async () => {
      const user = setupUser();
      renderPicker(["Model A"]);

      await openFromAdd(user);
      await user.click(settingsButton("Model C"));
      expectPane("Model C");
      await expectAnchoredAt(ADD);
    });

    // At max the unselected rows, settings included, are disabled, so the flag
    // is the reachable way to hide + with an unselected pane available.
    test("with multi-model off the list and an unselected model's pane sit on the row", async () => {
      mockSettings = { ...DEFAULT_SETTINGS, multi_model_chat_enabled: false };
      const user = setupUser();
      renderPicker(["Model A"]);

      await openFromPill(user, "Model A");
      expectPane("Model A");
      await expectAnchoredAt("Model A");

      await clickBack(user);
      expectList();
      await expectAnchoredAt(ROW);

      await user.click(settingsButton("Model C"));
      expectPane("Model C");
      await expectAnchoredAt(ROW);
    });

    test("a pill keeps its node from one model to two and back", async () => {
      const user = setupUser();
      renderPicker(["Model A"]);
      const pillA = pill("Model A");

      await openFromAdd(user);
      await user.click(row("Model B"));
      expect(pill("Model A")).toBe(pillA);

      await user.click(row("Model B"));
      expect(pillNames()).toEqual(["Model A"]);
      expect(pill("Model A")).toBe(pillA);
    });
  });

  // -------------------------------------------------------------------------
  // Row clicks toggle with the menu open
  // -------------------------------------------------------------------------

  describe("row toggle", () => {
    test("adds an unselected row once, keeps the menu open and the search text", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A"], callbacks);

      await openFromAdd(user);
      await typeSearch(user, "Model");
      const wrapper = openPopper();

      await user.click(row("Model C"));

      expect(callbacks.onAdd).toHaveBeenCalledTimes(1);
      expect(callbacks.onAdd).toHaveBeenCalledWith(selected("Model C"));
      expect(pillNames()).toEqual(["Model C", "Model A"]);
      expect(popperWrapper()).toBe(wrapper);
      expect(searchInput()).toHaveValue("Model");
    });

    // The default group follows the first group holding a selected model;
    // it must not re-apply while the menu is open.
    test.each([
      {
        action: "add",
        initial: ["Model E"],
        // Provider Two starts expanded; the user also opens Provider.
        expand: "Provider",
        click: "Model A",
        // In the group open from the start.
        stillShown: "Model F",
      },
      {
        action: "remove",
        initial: ["Model A", "Model E"],
        // Provider starts expanded; the user also opens Provider Two.
        expand: "Provider Two",
        click: "Model A",
        // In the group the user expanded.
        stillShown: "Model F",
      },
    ])(
      "keeps a group the user expanded when a row $action changes the first selected group",
      async ({ initial, expand, click, stillShown }) => {
        const user = setupUser();
        renderPicker(initial);

        await openFromAdd(user);
        const hidden = expand === "Provider" ? click : stillShown;
        expect(queryRow(hidden)).toBeNull();
        await user.click(groupHeader(expand));
        expect(queryRow(click)).not.toBeNull();
        expect(queryRow(stillShown)).not.toBeNull();

        await user.click(row(click));

        expect(popperWrapper()).not.toBeNull();
        expect(queryRow(click)).not.toBeNull();
        expect(queryRow(stillShown)).not.toBeNull();
      }
    );

    test("adds the third model with the menu open, hides + and disables every unselected row", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B"], callbacks);

      await openFromAdd(user);
      const wrapper = openPopper();
      await user.click(row("Model C"));

      expect(callbacks.onAdd).toHaveBeenCalledWith(selected("Model C"));
      expect(popperWrapper()).toBe(wrapper);
      expect(addButton()).toBeNull();
      expect(rowFieldset("Model D")).toBeDisabled();
      for (const name of ["Model A", "Model B", "Model C"]) {
        expectRowSelected(name, true);
        expect(rowFieldset(name)).not.toBeDisabled();
      }
    });

    test("removes a selected row with the menu open, calls onRemove with its index, keeps the search text", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B", "Model C"], callbacks);

      // At max there is no +, so the list is reached from a pill's pane.
      await openFromPill(user, "Model A");
      expectPane("Model A");
      await clickBack(user);
      await typeSearch(user, "Model");
      const wrapper = openPopper();

      await user.click(row("Model B"));

      expect(callbacks.onRemove).toHaveBeenCalledWith(1);
      expect(pillNames()).toEqual(["Model A", "Model C"]);
      expect(popperWrapper()).toBe(wrapper);
      expect(searchInput()).toHaveValue("Model");
      expectRowSelected("Model B", false);
      expect(rowFieldset("Model B")).not.toBeDisabled();
    });

    test("ignores a click on the sole selected row and keeps its settings button enabled", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A"], callbacks);

      await openFromAdd(user);
      await user.click(row("Model A"));

      expectNoCallbacks(callbacks);
      expect(pillNames()).toEqual(["Model A"]);
      expectRowSelected("Model A", true);
      expect(rowFieldset("Model A")).not.toBeDisabled();

      await user.click(settingsButton("Model A"));
      expectPane("Model A");
    });

    test("removing down to one keeps the menu open, drops the x and restores +", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B"], callbacks);

      await openFromAdd(user);
      await user.click(row("Model A"));

      expect(callbacks.onRemove).toHaveBeenCalledWith(0);
      expect(pillNames()).toEqual(["Model B"]);
      expect(pillX(pill("Model B"))).toBeNull();
      expect(addButton()).not.toBeNull();
      expect(popperWrapper()).not.toBeNull();
      await expectAnchoredAt(ADD);
    });
  });

  // -------------------------------------------------------------------------
  // Pill x
  // -------------------------------------------------------------------------

  describe("pill x", () => {
    test.each([
      {
        view: "list",
        initial: ["Model A", "Model B"],
        remove: "Model B",
        removedIndex: 1,
      },
      {
        view: "pane",
        initial: ["Model A", "Model B", "Model C"],
        remove: "Model B",
        removedIndex: 1,
      },
    ])(
      "pill x removes with the menu open in the $view and the menu in place",
      async ({ view, initial, remove, removedIndex }) => {
        const user = setupUser();
        const callbacks = makeCallbacks();
        renderPicker(initial, callbacks);

        if (view === "list") {
          await openFromAdd(user);
        } else {
          await openFromPill(user, "Model A");
          expectPane("Model A");
        }
        const wrapper = openPopper();

        await clickPillX(user, remove);

        expect(callbacks.onRemove).toHaveBeenCalledWith(removedIndex);
        expect(pillNames()).not.toContain(remove);
        expect(popperWrapper()).toBe(wrapper);
        if (view === "list") {
          expectList();
          await expectAnchoredAt(ADD);
        } else {
          expectPane("Model A");
          await expectAnchoredAt("Model A");
        }
      }
    );

    test("x on the pane's own model removes it and closes the menu", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B", "Model C"], callbacks);

      await openFromPill(user, "Model B");
      expectPane("Model B");

      await clickPillX(user, "Model B");

      expect(callbacks.onRemove).toHaveBeenCalledWith(1);
      expect(pillNames()).toEqual(["Model A", "Model C"]);
      await waitFor(() => expect(popperWrapper()).toBeNull());
    });

    test("the closing pane holds its removed pill's place through the exit animation", async () => {
      const user = setupUser();
      renderPicker(["Model A", "Model B", "Model C"]);

      await openFromPill(user, "Model B");
      expectPane("Model B");
      await expectAnchoredAt("Model B");
      const content = openPopper().firstElementChild;
      if (!(content instanceof HTMLElement))
        throw new Error("no popover content");
      // Presence keeps the content mounted until animationend, which jsdom never fires.
      content.style.animationName = "exit";
      const last = rectOf("Model B");

      await clickPillX(user, "Model B");

      expect(pillNames()).toEqual(["Model A", "Model C"]);
      expect(content).toHaveAttribute("data-state", "closed");
      // act flushes the re-measure; a waitFor would also pass on a stale transform.
      await act(async () => {
        fireEvent(window, new Event("resize"));
      });
      expect(popperXY()).toEqual({ x: last.right, y: last.top - SIDE_OFFSET });
    });
  });

  // -------------------------------------------------------------------------
  // Panes
  // -------------------------------------------------------------------------

  describe("panes", () => {
    test("pill click opens that model's pane with no add, remove or replace; back shows every selected model checked", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B"], callbacks);

      await openFromPill(user, "Model B");

      expectPane("Model B");
      expectNoCallbacks(callbacks);
      expect(pillNames()).toEqual(["Model A", "Model B"]);

      await clickBack(user);
      expectList();
      expectRowSelected("Model A", true);
      expectRowSelected("Model B", true);
      for (const name of ["Model C", "Model D"]) {
        expectRowSelected(name, false);
        expect(rowFieldset(name)).not.toBeDisabled();
      }
    });

    test("settings button opens the pane without selecting, on an unselected and a selected row", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A"], callbacks);

      await openFromAdd(user);
      await user.click(settingsButton("Model C"));

      expectPane("Model C");
      expectNoCallbacks(callbacks);
      expect(pillNames()).toEqual(["Model A"]);

      await clickBack(user);
      await user.click(settingsButton("Model A"));

      expectPane("Model A");
      expectNoCallbacks(callbacks);
      expect(pillNames()).toEqual(["Model A"]);
    });

    test("pill clicks while open switch panes, a repeat reopens the pane, + returns to the list", async () => {
      const user = setupUser();
      renderPicker(["Model A", "Model B"]);

      await openFromAdd(user);
      const wrapper = openPopper();

      await user.click(pill("Model B"));
      expect(popperWrapper()).toBe(wrapper);
      expectPane("Model B");

      await user.click(pill("Model A"));
      expect(popperWrapper()).toBe(wrapper);
      expectPane("Model A");

      await clickBack(user);
      expectList();
      await user.click(pill("Model A"));
      expect(popperWrapper()).toBe(wrapper);
      expectPane("Model A");

      await openFromAdd(user);
      expect(popperWrapper()).toBe(wrapper);
      expectList();
    });
  });

  // -------------------------------------------------------------------------
  // Closing
  // -------------------------------------------------------------------------

  describe("closing", () => {
    test.each([
      {
        how: "Escape",
        dismiss: (user: User) => user.keyboard("{Escape}"),
      },
      {
        how: "an outside pointerdown",
        dismiss: (user: User) => user.click(document.body),
      },
    ])("$how closes the menu", async ({ dismiss }) => {
      const user = setupUser();
      renderPicker(["Model A", "Model B"]);

      await openFromAdd(user);
      await dismiss(user);

      await waitFor(() => expect(popperWrapper()).toBeNull());
    });

    test("stays open on + click, pill click and pill x", async () => {
      const user = setupUser();
      renderPicker(["Model A", "Model B"]);

      await openFromAdd(user);
      const wrapper = openPopper();

      await openFromAdd(user);
      expect(popperWrapper()).toBe(wrapper);

      await user.click(pill("Model A"));
      expect(popperWrapper()).toBe(wrapper);

      await clickPillX(user, "Model B");
      expect(popperWrapper()).toBe(wrapper);
    });
  });

  // -------------------------------------------------------------------------
  // Workspace flags
  // -------------------------------------------------------------------------

  describe("flags", () => {
    test("multi-model off: unselected rows are enabled, a click replaces the sole model with the menu open, the selected row is a no-op, no x and no +", async () => {
      mockSettings = { ...DEFAULT_SETTINGS, multi_model_chat_enabled: false };
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A"], callbacks);

      expect(addButton()).toBeNull();
      expect(pillX(pill("Model A"))).toBeNull();

      await openFromPill(user, "Model A");
      expectPane("Model A");
      await clickBack(user);
      const wrapper = openPopper();

      expect(rowFieldset("Model C")).not.toBeDisabled();
      await user.click(row("Model C"));

      expect(callbacks.onReplace).toHaveBeenCalledWith(0, selected("Model C"));
      expect(callbacks.onAdd).not.toHaveBeenCalled();
      expect(pillNames()).toEqual(["Model C"]);
      expect(pillX(pill("Model C"))).toBeNull();
      expect(addButton()).toBeNull();
      expect(popperWrapper()).toBe(wrapper);

      callbacks.onReplace.mockClear();
      await user.click(row("Model C"));
      expectNoCallbacks(callbacks);
      expect(pillNames()).toEqual(["Model C"]);
    });

    test("reasoning override off: pill click opens the list with no settings buttons, and rows toggle", async () => {
      mockSettings = { ...DEFAULT_SETTINGS, reasoning_override_enabled: false };
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B"], callbacks);

      await openFromPill(user, "Model A");

      expectList();
      expect(
        within(openPopper()).queryByRole("button", {
          name: /^modelSettingsButton\.ariaLabel/,
        })
      ).toBeNull();

      await user.click(row("Model C"));
      expect(callbacks.onAdd).toHaveBeenCalledWith(selected("Model C"));
      expect(callbacks.onReplace).not.toHaveBeenCalled();
      expect(pillNames()).toEqual(["Model C", "Model A", "Model B"]);
    });
  });

  // -------------------------------------------------------------------------
  // Keyboard
  // -------------------------------------------------------------------------

  describe("keyboard", () => {
    test("Enter on a focused row toggles it, Enter on a focused pill opens its pane without removing", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B"], callbacks);

      await openFromAdd(user);
      const wrapper = openPopper();

      row("Model C").focus();
      await user.keyboard("{Enter}");
      expect(callbacks.onAdd).toHaveBeenCalledWith(selected("Model C"));
      expect(pillNames()).toEqual(["Model C", "Model A", "Model B"]);
      expect(popperWrapper()).toBe(wrapper);

      row("Model A").focus();
      await user.keyboard("{Enter}");
      expect(callbacks.onRemove).toHaveBeenCalledWith(1);
      expect(pillNames()).toEqual(["Model C", "Model B"]);

      callbacks.onRemove.mockClear();
      pill("Model B").focus();
      await user.keyboard("{Enter}");
      expect(callbacks.onRemove).not.toHaveBeenCalled();
      expect(pillNames()).toEqual(["Model C", "Model B"]);
      expect(popperWrapper()).toBe(wrapper);
      expectPane("Model B");
    });
  });
});
