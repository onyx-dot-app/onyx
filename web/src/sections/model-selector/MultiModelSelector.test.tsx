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
async function expectAnchoredAt(anchor: string | DOMRect) {
  const rect = typeof anchor === "string" ? rectOf(anchor) : anchor;
  fireEvent(window, new Event("resize"));
  await waitFor(() =>
    expect(popperXY()).toEqual({
      x: rect.right,
      y: rect.top - SIDE_OFFSET,
    })
  );
}

/** Re-measures, then checks the panel did not leave `rect`; a waitFor would pass on a stale transform. */
async function expectStillAt(rect: DOMRect) {
  await act(async () => {
    fireEvent(window, new Event("resize"));
  });
  expect(popperXY()).toEqual({ x: rect.right, y: rect.top - SIDE_OFFSET });
}

/** Presence keeps the content mounted until animationend, which jsdom never fires. */
function holdExitAnimation(): HTMLElement {
  const content = openPopper().firstElementChild;
  if (!(content instanceof HTMLElement)) throw new Error("no popover content");
  content.style.animationName = "exit";
  return content;
}

async function expectClosed() {
  await waitFor(() => expect(popperWrapper()).toBeNull());
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

/** A list row; a collapsed provider group's fold is aria-hidden, so its rows are not found. */
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

function expectRowEnabled(displayName: string, isEnabled: boolean) {
  if (isEnabled) expect(rowFieldset(displayName)).not.toBeDisabled();
  else expect(rowFieldset(displayName)).toBeDisabled();
}

function settingsButton(displayName: string): HTMLElement {
  return within(openPopper()).getByRole("button", {
    name: `modelSettingsButton.ariaLabel:${displayName}`,
  });
}

function querySettingsButtons(): HTMLElement[] {
  return within(openPopper()).queryAllByRole("button", {
    name: /^modelSettingsButton\.ariaLabel/,
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

function requireAddButton(): HTMLElement {
  const add = addButton();
  if (!add) throw new Error("add button is hidden");
  return add;
}

async function openFromAdd(user: User) {
  await user.click(requireAddButton());
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

const CALLBACK_NAMES: (keyof Callbacks)[] = ["onAdd", "onRemove", "onReplace"];

function expectNoCallbacks(callbacks: Callbacks) {
  for (const name of CALLBACK_NAMES) {
    expect(callbacks[name]).not.toHaveBeenCalled();
  }
}

/** `name` fired once with `args` and no other callback fired. */
function expectOnlyCall(
  callbacks: Callbacks,
  name: keyof Callbacks,
  ...args: unknown[]
) {
  for (const other of CALLBACK_NAMES) {
    if (other === name) continue;
    expect(callbacks[other]).not.toHaveBeenCalled();
  }
  expect(callbacks[name]).toHaveBeenCalledTimes(1);
  expect(callbacks[name]).toHaveBeenCalledWith(...args);
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
    test("+ opens the add list on + and the rect stays when + moves", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B"], callbacks);

      await openFromAdd(user);
      expectList();
      await expectAnchoredAt(ADD);
      for (const name of ["Model A", "Model B"]) {
        expectRowSelected(name, true);
        expectRowEnabled(name, true);
      }
      for (const name of ["Model C", "Model D"]) {
        expectRowSelected(name, false);
        expectRowEnabled(name, true);
      }
      expectNoCallbacks(callbacks);

      const atOpen = rectOf(ADD);
      setRect(ADD, new DOMRect(220, 704, 32, 32));
      await expectStillAt(atOpen);
    });

    test("a pill opens its switch list on the pill and the rect stays when the pill moves", async () => {
      const user = setupUser();
      renderPicker(["Model A", "Model B"]);

      await openFromPill(user, "Model B");
      expectList();
      await expectAnchoredAt("Model B");

      const atOpen = rectOf("Model B");
      setRect("Model B", new DOMRect(760, 704, 90, 32));
      await expectStillAt(atOpen);
    });

    test("the third add closes the menu and the fading content holds +'s rect after + is gone", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B"], callbacks);

      await openFromAdd(user);
      await expectAnchoredAt(ADD);
      const atOpen = rectOf(ADD);
      const content = holdExitAnimation();

      await user.click(row("Model C"));

      expect(callbacks.onAdd).toHaveBeenCalledWith(selected("Model C"));
      expect(addButton()).toBeNull();
      expect(content).toHaveAttribute("data-state", "closed");
      await expectStillAt(atOpen);
    });

    test("a replace closes and the fading content holds the pill's rect after the pill remounted", async () => {
      const user = setupUser();
      renderPicker(["Model A", "Model B", "Model C"]);

      await openFromPill(user, "Model B");
      await expectAnchoredAt("Model B");
      const atOpen = rectOf("Model B");
      const content = holdExitAnimation();

      await user.click(row("Model D"));

      expect(pillNames()).toEqual(["Model A", "Model D", "Model C"]);
      expect(content).toHaveAttribute("data-state", "closed");
      await expectStillAt(atOpen);
    });

    test("a pill keeps its node from one model to two and back", async () => {
      const user = setupUser();
      renderPicker(["Model A"]);
      const pillA = pill("Model A");

      await openFromAdd(user);
      await user.click(row("Model B"));
      expect(pillNames()).toEqual(["Model B", "Model A"]);
      expect(pill("Model A")).toBe(pillA);

      await clickPillX(user, "Model B");
      expect(pillNames()).toEqual(["Model A"]);
      expect(pill("Model A")).toBe(pillA);
    });
  });

  // -------------------------------------------------------------------------
  // Add list
  // -------------------------------------------------------------------------

  describe("add list", () => {
    test("adds once and closes", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A"], callbacks);

      await openFromAdd(user);
      await user.click(row("Model C"));

      expectOnlyCall(callbacks, "onAdd", selected("Model C"));
      expect(pillNames()).toEqual(["Model C", "Model A"]);
      await expectClosed();
    });

    test("a selected row removes by index and closes", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B"], callbacks);

      await openFromAdd(user);
      await user.click(row("Model B"));

      expect(callbacks.onRemove).toHaveBeenCalledTimes(1);
      expect(callbacks.onRemove).toHaveBeenCalledWith(1);
      expect(callbacks.onAdd).not.toHaveBeenCalled();
      expect(pillNames()).toEqual(["Model A"]);
      await expectClosed();
    });

    test("the sole selected row is a no-op with its settings enabled", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A"], callbacks);

      await openFromAdd(user);
      const wrapper = openPopper();
      await user.click(row("Model A"));

      expectNoCallbacks(callbacks);
      expect(popperWrapper()).toBe(wrapper);
      expectRowSelected("Model A", true);
      expectRowEnabled("Model A", true);

      await user.click(settingsButton("Model A"));
      expectPane("Model A");
    });

    test("settings opens the pane without selecting, back keeps the search and groups", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A"], callbacks);

      await openFromAdd(user);
      await user.click(groupHeader("Provider Two"));
      await user.click(settingsButton("Model E"));

      expectPane("Model E");
      expectNoCallbacks(callbacks);
      expect(pillNames()).toEqual(["Model A"]);
      await expectStillAt(rectOf(ADD));

      await clickBack(user);
      expectList();
      expect(queryRow("Model F")).not.toBeNull();

      await typeSearch(user, "Model");
      await user.click(settingsButton("Model A"));

      expectPane("Model A");
      expectNoCallbacks(callbacks);
      expect(pillNames()).toEqual(["Model A"]);
      await expectStillAt(rectOf(ADD));

      await clickBack(user);
      expect(searchInput()).toHaveValue("Model");
    });

    // The default group follows the first group holding a selected model; it
    // must not re-apply while the closing content fades out.
    test("the fading content keeps an expanded group", async () => {
      const user = setupUser();
      renderPicker(["Model E"]);

      await openFromAdd(user);
      expect(queryRow("Model A")).toBeNull();
      await user.click(groupHeader("Provider"));
      const content = holdExitAnimation();

      await user.click(row("Model A"));

      expect(pillNames()).toEqual(["Model A", "Model E"]);
      expect(content).toHaveAttribute("data-state", "closed");
      expect(queryRow("Model A")).not.toBeNull();
      expect(queryRow("Model F")).not.toBeNull();
    });

    test("a second click while closing is ignored", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A"], callbacks);

      await openFromAdd(user);
      const content = holdExitAnimation();
      await user.click(row("Model C"));
      expect(content).toHaveAttribute("data-state", "closed");

      await user.click(row("Model C"));

      expect(callbacks.onAdd).toHaveBeenCalledTimes(1);
      expect(callbacks.onRemove).not.toHaveBeenCalled();
      expect(pillNames()).toEqual(["Model C", "Model A"]);
    });
  });

  // -------------------------------------------------------------------------
  // Switch list
  // -------------------------------------------------------------------------

  describe("switch list", () => {
    test("checks the pill's model, disables the other selected rows, enables the rest, no callbacks", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B", "Model C"], callbacks);

      await openFromPill(user, "Model B");

      expectList();
      expectRowSelected("Model B", true);
      expectRowEnabled("Model B", true);
      for (const name of ["Model A", "Model C"]) {
        expectRowSelected(name, false);
        expectRowEnabled(name, false);
        expect(settingsButton(name)).toBeDisabled();
      }
      expectRowSelected("Model D", false);
      expectRowEnabled("Model D", true);
      expectNoCallbacks(callbacks);
    });

    test("a pick replaces by index and closes", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B", "Model C"], callbacks);

      await openFromPill(user, "Model B");
      await user.click(row("Model D"));

      expectOnlyCall(callbacks, "onReplace", 1, selected("Model D"));
      expect(pillNames()).toEqual(["Model A", "Model D", "Model C"]);
      await expectClosed();
    });

    test("own row closes with no callback", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B"], callbacks);

      await openFromPill(user, "Model B");
      await user.click(row("Model B"));

      expectNoCallbacks(callbacks);
      expect(pillNames()).toEqual(["Model A", "Model B"]);
      await expectClosed();
    });

    test("settings opens the pane, back returns to the same switch list", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B", "Model C"], callbacks);

      await openFromPill(user, "Model B");
      await expectAnchoredAt("Model B");

      await user.click(settingsButton("Model D"));
      expectPane("Model D");
      expectNoCallbacks(callbacks);
      await expectStillAt(rectOf("Model B"));

      await clickBack(user);
      expectList();
      expectRowSelected("Model B", true);
      expectRowEnabled("Model A", false);
      expectRowEnabled("Model C", false);

      await user.click(settingsButton("Model B"));
      expectPane("Model B");
      expectNoCallbacks(callbacks);
      expect(pillNames()).toEqual(["Model A", "Model B", "Model C"]);
    });
  });

  // -------------------------------------------------------------------------
  // Closing and switching menus
  // -------------------------------------------------------------------------

  describe("closing and switching", () => {
    test.each([
      { how: "Escape", dismiss: (user: User) => user.keyboard("{Escape}") },
      {
        how: "an outside click",
        dismiss: (user: User) => user.click(document.body),
      },
    ])("$how closes the menu", async ({ dismiss }) => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B"], callbacks);

      await openFromAdd(user);
      await dismiss(user);
      await expectClosed();

      await openFromPill(user, "Model A");
      await dismiss(user);
      await expectClosed();
      expectNoCallbacks(callbacks);
    });

    test.each([
      { view: "add list", opener: ADD, pane: null, remove: "Model B" },
      { view: "switch list", opener: "Model B", pane: null, remove: "Model A" },
      {
        view: "own switch list",
        opener: "Model B",
        pane: null,
        remove: "Model B",
      },
      { view: "pane", opener: ADD, pane: "Model A", remove: "Model B" },
      {
        view: "own pane",
        opener: "Model B",
        pane: "Model B",
        remove: "Model B",
      },
    ])(
      "x closes from the $view outright and the next open starts fresh",
      async ({ opener, pane, remove }) => {
        const user = setupUser();
        const callbacks = makeCallbacks();
        const initial = ["Model A", "Model B"];
        renderPicker(initial, callbacks);

        if (opener === ADD) await openFromAdd(user);
        else await openFromPill(user, opener);
        await expectAnchoredAt(opener);
        if (pane) {
          await user.click(settingsButton(pane));
          expectPane(pane);
        }
        holdExitAnimation();

        await clickPillX(user, remove);

        expect(popperWrapper()).toBeNull();
        expectOnlyCall(callbacks, "onRemove", initial.indexOf(remove));
        expect(pillNames()).not.toContain(remove);

        await openFromAdd(user);
        expectList();
        expect(searchInput()).toHaveValue("");
        await expectAnchoredAt(ADD);
      }
    );

    test("x with the menu closed only removes", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B"], callbacks);

      await clickPillX(user, "Model B");

      expectOnlyCall(callbacks, "onRemove", 1);
      expect(pillNames()).toEqual(["Model A"]);
      expect(popperWrapper()).toBeNull();
    });

    test("a pill click over an open pane starts on the switch list", async () => {
      const user = setupUser();
      renderPicker(["Model A", "Model B"]);

      await openFromAdd(user);
      await typeSearch(user, "Model");
      await user.click(settingsButton("Model D"));
      expectPane("Model D");

      await openFromPill(user, "Model B");
      expectList();
      expect(searchInput()).toHaveValue("");
      expectRowSelected("Model B", true);
      await expectAnchoredAt("Model B");
    });

    test("clicking the open menu's own opener closes it", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B"], callbacks);

      await openFromAdd(user);
      await user.click(requireAddButton());
      await expectClosed();

      await openFromPill(user, "Model B");
      await user.click(pill("Model B"));
      await expectClosed();
      expectNoCallbacks(callbacks);
    });

    test("a click on +'s icon over an open switch list opens the add list", async () => {
      const user = setupUser();
      renderPicker(["Model A", "Model B"]);

      await openFromPill(user, "Model B");
      const icon = requireAddButton().querySelector("svg");
      if (!icon) throw new Error("+ has no icon");
      await user.click(icon);

      expectList();
      expectRowSelected("Model A", true);
      expectRowEnabled("Model A", true);
      await expectAnchoredAt(ADD);
    });

    test("+ then pill then + switches menus with a fresh rect each time", async () => {
      const user = setupUser();
      renderPicker(["Model A", "Model B"]);

      await openFromAdd(user);
      await expectAnchoredAt(ADD);

      await openFromPill(user, "Model B");
      expectRowSelected("Model B", true);
      expectRowSelected("Model A", false);
      expectRowEnabled("Model A", false);
      await expectAnchoredAt("Model B");

      await openFromPill(user, "Model A");
      expectRowSelected("Model A", true);
      expectRowEnabled("Model B", false);
      await expectAnchoredAt("Model A");

      setRect(ADD, new DOMRect(220, 704, 32, 32));
      await openFromAdd(user);
      expectRowSelected("Model A", true);
      expectRowSelected("Model B", true);
      expectRowEnabled("Model B", true);
      await expectAnchoredAt(ADD);
    });
  });

  // -------------------------------------------------------------------------
  // Workspace flags
  // -------------------------------------------------------------------------

  describe("flags", () => {
    test("multi-model off: no +, no x, pick replaces index 0 and closes", async () => {
      mockSettings = { ...DEFAULT_SETTINGS, multi_model_chat_enabled: false };
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A"], callbacks);

      expect(addButton()).toBeNull();
      expect(pillX(pill("Model A"))).toBeNull();

      await openFromPill(user, "Model A");
      expectList();
      await expectAnchoredAt("Model A");
      expectRowSelected("Model A", true);
      expectRowEnabled("Model C", true);

      await user.click(row("Model C"));

      expect(callbacks.onReplace).toHaveBeenCalledTimes(1);
      expect(callbacks.onReplace).toHaveBeenCalledWith(0, selected("Model C"));
      expect(callbacks.onAdd).not.toHaveBeenCalled();
      expect(pillNames()).toEqual(["Model C"]);
      expect(pillX(pill("Model C"))).toBeNull();
      await expectClosed();

      callbacks.onReplace.mockClear();
      await openFromPill(user, "Model C");
      await user.click(row("Model C"));
      expectNoCallbacks(callbacks);
      await expectClosed();
    });

    test("multi-model off with two restored models disables the other selected row", async () => {
      mockSettings = { ...DEFAULT_SETTINGS, multi_model_chat_enabled: false };
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B"], callbacks);

      expect(addButton()).toBeNull();

      await openFromPill(user, "Model B");
      expectRowSelected("Model B", true);
      expectRowEnabled("Model A", false);
      expectRowEnabled("Model D", true);

      await user.click(row("Model D"));

      expect(callbacks.onReplace).toHaveBeenCalledWith(1, selected("Model D"));
      expect(pillNames()).toEqual(["Model A", "Model D"]);
      await expectClosed();
    });

    test("reasoning off: no settings buttons, lists unchanged", async () => {
      mockSettings = { ...DEFAULT_SETTINGS, reasoning_override_enabled: false };
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B"], callbacks);

      await openFromPill(user, "Model A");
      expectList();
      expect(querySettingsButtons()).toEqual([]);
      expectRowEnabled("Model B", false);

      await user.click(row("Model C"));
      expect(callbacks.onReplace).toHaveBeenCalledWith(0, selected("Model C"));
      await expectClosed();

      await openFromAdd(user);
      expect(querySettingsButtons()).toEqual([]);
      await user.click(row("Model D"));
      expect(callbacks.onAdd).toHaveBeenCalledWith(selected("Model D"));
      expect(pillNames()).toEqual(["Model D", "Model C", "Model B"]);
      await expectClosed();
    });
  });

  // -------------------------------------------------------------------------
  // Keyboard
  // -------------------------------------------------------------------------

  describe("keyboard", () => {
    test("Enter on +, a pill and a row", async () => {
      const user = setupUser();
      const callbacks = makeCallbacks();
      renderPicker(["Model A", "Model B"], callbacks);

      const add = requireAddButton();
      act(() => add.focus());
      await user.keyboard("{Enter}");
      expectList();
      await expectAnchoredAt(ADD);

      act(() => row("Model C").focus());
      await user.keyboard("{Enter}");
      expect(callbacks.onAdd).toHaveBeenCalledWith(selected("Model C"));
      expect(pillNames()).toEqual(["Model C", "Model A", "Model B"]);
      await expectClosed();

      act(() => pill("Model B").focus());
      await user.keyboard("{Enter}");
      expect(callbacks.onRemove).not.toHaveBeenCalled();
      expectList();
      expectRowSelected("Model B", true);
      await expectAnchoredAt("Model B");

      act(() => row("Model D").focus());
      await user.keyboard("{Enter}");
      expect(callbacks.onReplace).toHaveBeenCalledWith(2, selected("Model D"));
      expect(pillNames()).toEqual(["Model C", "Model A", "Model D"]);
      await expectClosed();
    });
  });
});
