import userEvent from "@testing-library/user-event";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@tests/setup/test-utils";
import { toast } from "@opal/layouts";
import { uploadBrowserFiles } from "@/lib/chat/browser/api";
import { useBrowserStream } from "@/lib/chat/browser/hooks";
import { BrowserPanel } from "@/sections/chat/browser/BrowserPanel";

jest.mock("@/lib/chat/browser/api", () => ({
  ...jest.requireActual("@/lib/chat/browser/api"),
  uploadBrowserFiles: jest.fn(),
}));

/** A websocket the test drives by hand. */
class FakeSocket extends EventTarget {
  static instances: FakeSocket[] = [];
  readyState = 0;
  binaryType = "blob";
  sent: unknown[] = [];
  constructor(readonly url: string) {
    super();
    FakeSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.closeWith(1000);
  }
  open() {
    this.readyState = 1;
    this.dispatchEvent(new Event("open"));
  }
  receive(message: object) {
    this.dispatchEvent(
      Object.assign(new Event("message"), { data: JSON.stringify(message) })
    );
  }
  closeWith(code: number) {
    if (this.readyState === 3) return;
    this.readyState = 3;
    this.dispatchEvent(Object.assign(new Event("close"), { code }));
  }
}

const TAB = {
  id: "t1",
  url: "https://example.com/",
  title: "Example Domain",
  loading: false,
  dialog: null,
};

function socket(): FakeSocket {
  const last = FakeSocket.instances.at(-1);
  if (!last) throw new Error("The panel opened no websocket");
  return last;
}

interface ViewerProps {
  active: boolean;
}

/** The view on a stream, as the chat's right panel wires them. */
function Viewer({ active }: ViewerProps) {
  const stream = useBrowserStream({
    sessionId: "chat-1",
    active,
    onDownload: () => undefined,
    onError: () => undefined,
  });
  return <BrowserPanel sessionId="chat-1" stream={stream} />;
}

function renderPanel(active = true) {
  return render(<Viewer active={active} />);
}

const originalWebSocket = globalThis.WebSocket;

beforeEach(() => {
  FakeSocket.instances = [];
  Object.defineProperty(globalThis, "WebSocket", {
    configurable: true,
    writable: true,
    value: FakeSocket,
  });
  jest.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
});

afterEach(() => {
  Object.defineProperty(globalThis, "WebSocket", {
    configurable: true,
    writable: true,
    value: originalWebSocket,
  });
  jest.restoreAllMocks();
});

test("an inactive stream opens no connection", () => {
  renderPanel(false);
  expect(FakeSocket.instances).toHaveLength(0);
});

test("without a backend it shows the disconnected state with a retry", () => {
  jest.useFakeTimers();
  try {
    renderPanel();
    act(() => socket().closeWith(1006));
    expect(screen.getByText("The browser disconnected")).toBeInTheDocument();
    act(() => screen.getByRole("button", { name: "Retry" }).click());
    expect(FakeSocket.instances).toHaveLength(2);
  } finally {
    jest.useRealTimers();
  }
});

test("connects that never open stop with a retry", () => {
  jest.useFakeTimers();
  try {
    renderPanel();
    for (let i = 0; i < 6; i++) {
      act(() => socket().closeWith(1006));
      act(() => jest.advanceTimersByTime(10_000));
    }
    expect(screen.getByText("Could not reach the browser")).toBeInTheDocument();
    expect(FakeSocket.instances).toHaveLength(6);
    act(() => screen.getByRole("button", { name: "Retry" }).click());
    expect(FakeSocket.instances).toHaveLength(7);
  } finally {
    jest.useRealTimers();
  }
});

test("a forbidden close shows that the browser is off", () => {
  renderPanel();
  act(() => socket().closeWith(4403));
  expect(screen.getByText("The browser is off")).toBeInTheDocument();
});

test("shows the chat's tabs and hands control over", () => {
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({ type: "tabs", tabs: [TAB], selected: "t1" });
    socket().receive({ type: "control", controller: "agent" });
  });
  expect(screen.getByText("The agent controls this tab")).toBeInTheDocument();
  // Only the controller can type a URL
  expect(
    screen.queryByRole("textbox", { name: "Address" })
  ).not.toBeInTheDocument();

  act(() => screen.getByRole("button", { name: "Take control" }).click());
  expect(socket().sent.at(-1)).toEqual({ type: "takeControl" });

  act(() => socket().receive({ type: "control", controller: "you" }));
  expect(screen.getByText("You control this tab")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "Address" })).toHaveValue(
    "https://example.com/"
  );
  act(() => screen.getByRole("button", { name: "Back" }).click());
  expect(socket().sent.at(-1)).toEqual({ type: "history", delta: -1 });
  act(() => screen.getByRole("button", { name: "Release control" }).click());
  expect(socket().sent.at(-1)).toEqual({ type: "releaseControl" });
});

test("a page without a URL says to type one, and a page with none open offers a new tab", () => {
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({
      type: "tabs",
      tabs: [{ ...TAB, url: "about:blank", title: "" }],
      selected: "t1",
    });
  });
  expect(screen.getByText("No page yet")).toBeInTheDocument();
  expect(
    screen.getByText("Type a URL above to open a page.")
  ).toBeInTheDocument();

  act(() => socket().receive({ type: "tabs", tabs: [], selected: null }));
  expect(screen.getByText("No page is open")).toBeInTheDocument();
  act(() => screen.getByRole("button", { name: "New tab" }).click());
  expect(socket().sent.at(-1)).toEqual({ type: "newTab" });
});

test("an edited URL stays with its tab", () => {
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({
      type: "tabs",
      tabs: [TAB, { ...TAB, id: "t2", url: "https://second.example/" }],
      selected: "t1",
    });
    socket().receive({ type: "control", controller: "you" });
  });
  const address = () => screen.getByRole("textbox", { name: "Address" });
  act(() => {
    fireEvent.change(address(), { target: { value: "typed.example" } });
  });
  expect(address()).toHaveValue("typed.example");
  act(() =>
    socket().receive({
      type: "tabs",
      tabs: [TAB, { ...TAB, id: "t2", url: "https://second.example/" }],
      selected: "t2",
    })
  );
  expect(address()).toHaveValue("https://second.example/");
});

test("the agent's cursor waits for a frame and shows only on the tab that it moved on", async () => {
  // jsdom lays nothing out, so the canvas gets a size here
  jest.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(400);
  jest.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(300);
  mockFrames();
  const { container } = renderPanel();
  const tabs = [TAB, { ...TAB, id: "t2" }];
  const cursor = () => container.querySelector("[data-agent-browser-cursor]");
  act(() => {
    socket().open();
    socket().receive({ type: "tabs", tabs, selected: "t1" });
    socket().receive({ type: "viewport", width: 1280, height: 800 });
    socket().receive({
      type: "pointer",
      phase: "move",
      x: 1,
      y: 1,
      sequence: 1,
    });
  });
  expect(cursor()).toBeNull();
  await paintFrame(container);
  expect(cursor()).not.toBeNull();
  act(() => socket().receive({ type: "tabs", tabs, selected: "t2" }));
  await paintFrame(container);
  expect(cursor()).toBeNull();
  act(() => socket().receive({ type: "tabs", tabs, selected: "t1" }));
  await paintFrame(container);
  expect(cursor()).not.toBeNull();
});

test("a page dialog asks the controller to answer it", () => {
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({
      type: "tabs",
      tabs: [{ ...TAB, dialog: { type: "confirm", message: "Leave page?" } }],
      selected: "t1",
    });
    socket().receive({ type: "control", controller: "agent" });
  });
  expect(screen.getByText("Leave page?")).toBeInTheDocument();
  expect(screen.getByText("Take control to respond.")).toBeInTheDocument();

  act(() => socket().receive({ type: "control", controller: "you" }));
  act(() => screen.getByRole("button", { name: "Accept" }).click());
  expect(socket().sent.at(-1)).toEqual({ type: "dialog", accept: true });
});

test("a file chooser can be cancelled", () => {
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({ type: "tabs", tabs: [TAB], selected: "t1" });
    socket().receive({ type: "control", controller: "you" });
    socket().receive({
      type: "fileChooser",
      id: "f1",
      multiple: false,
    });
  });
  expect(screen.getByText("The page asks for a file.")).toBeInTheDocument();
  act(() => screen.getByRole("button", { name: "Cancel" }).click());
  expect(socket().sent.at(-1)).toEqual({
    type: "fileChooser",
    id: "f1",
    paths: [],
  });
  expect(
    screen.queryByText("The page asks for a file.")
  ).not.toBeInTheDocument();
});

test("an upload that ends after its file chooser closed does not answer", async () => {
  let finishUpload: (paths: string[]) => void = () => undefined;
  jest.mocked(uploadBrowserFiles).mockReturnValue(
    new Promise((resolve) => {
      finishUpload = resolve;
    })
  );
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({ type: "tabs", tabs: [TAB], selected: "t1" });
    socket().receive({ type: "control", controller: "you" });
    socket().receive({ type: "fileChooser", id: "f1", multiple: false });
  });
  await userEvent.upload(
    screen.getByLabelText("Files for the page"),
    new File(["a"], "a.txt")
  );
  await waitFor(() => expect(uploadBrowserFiles).toHaveBeenCalled());
  // The page gives up on the chooser and asks again
  act(() => {
    socket().receive({ type: "fileChooserClosed", id: "f1" });
    socket().receive({ type: "fileChooser", id: "f2", multiple: false });
  });
  await act(async () => finishUpload(["browser-uploads/a.txt"]));
  expect(socket().sent).toEqual([]);
  expect(screen.getByText("The page asks for a file.")).toBeInTheDocument();
});

test("Shift+Escape leaves the page and lets go of the keys held on it", () => {
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({ type: "tabs", tabs: [TAB], selected: "t1" });
    socket().receive({ type: "control", controller: "you" });
  });
  const input = screen.getByRole("textbox", { name: "Browser page" });
  act(() => input.focus());
  fireEvent.keyDown(input, { key: "Shift", code: "ShiftLeft", shiftKey: true });
  fireEvent.keyDown(input, { key: "Escape", code: "Escape", shiftKey: true });
  expect(input).not.toHaveFocus();
  expect(socket().sent).toEqual([
    {
      type: "key",
      action: "down",
      key: "Shift",
      code: "ShiftLeft",
      keyCode: 0,
      modifiers: 8,
    },
    {
      type: "key",
      action: "up",
      key: "Shift",
      code: "ShiftLeft",
      keyCode: 0,
      modifiers: 0,
    },
  ]);
});

test("the file chooser goes when the selected tab changes", () => {
  renderPanel();
  const tabs = [TAB, { ...TAB, id: "t2" }];
  act(() => {
    socket().open();
    socket().receive({ type: "tabs", tabs, selected: "t1" });
    socket().receive({ type: "control", controller: "you" });
    socket().receive({ type: "fileChooser", id: "f1", multiple: false });
  });
  expect(screen.getByText("The page asks for a file.")).toBeInTheDocument();
  act(() => socket().receive({ type: "tabs", tabs, selected: "t2" }));
  expect(
    screen.queryByText("The page asks for a file.")
  ).not.toBeInTheDocument();
});

test("the prompt overlay shows only while the page asks something", () => {
  const { container } = renderPanel();
  const overlay = () => container.querySelector("[data-browser-prompts]");
  act(() => {
    socket().open();
    socket().receive({ type: "tabs", tabs: [TAB], selected: "t1" });
    socket().receive({ type: "control", controller: "you" });
  });
  expect(overlay()).toBeNull();
  act(() =>
    socket().receive({ type: "fileChooser", id: "f1", multiple: false })
  );
  expect(overlay()).not.toBeNull();
});

test("a long paste goes to the page in chunks, in order", () => {
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({ type: "tabs", tabs: [TAB], selected: "t1" });
    socket().receive({ type: "control", controller: "you" });
  });
  const text = "a".repeat(10_000) + "b".repeat(10_000) + "c";
  fireEvent.paste(screen.getByRole("textbox", { name: "Browser page" }), {
    clipboardData: { getData: () => text },
  });
  expect(socket().sent).toEqual([
    { type: "text", text: "a".repeat(10_000) },
    { type: "text", text: "b".repeat(10_000) },
    { type: "text", text: "c" },
  ]);
});

test("each tab keeps its URL draft until its navigate is sent", () => {
  renderPanel();
  const tabs = [TAB, { ...TAB, id: "t2", url: "https://second.example/" }];
  act(() => {
    socket().open();
    socket().receive({ type: "tabs", tabs, selected: "t1" });
    socket().receive({ type: "control", controller: "you" });
  });
  const address = () => screen.getByRole("textbox", { name: "Address" });
  fireEvent.change(address(), { target: { value: "one.example" } });
  act(() => socket().receive({ type: "tabs", tabs, selected: "t2" }));
  fireEvent.change(address(), { target: { value: "two.example" } });
  act(() => socket().receive({ type: "tabs", tabs, selected: "t1" }));
  expect(address()).toHaveValue("one.example");
  // A navigate that is not sent keeps the draft
  socket().readyState = 0;
  fireEvent.keyDown(address(), { key: "Enter" });
  expect(address()).toHaveValue("one.example");
  socket().readyState = 1;
  fireEvent.keyDown(address(), { key: "Enter" });
  expect(socket().sent.at(-1)).toEqual({
    type: "navigate",
    url: "one.example",
  });
  expect(address()).toHaveValue("https://example.com/");
  act(() => socket().receive({ type: "tabs", tabs, selected: "t2" }));
  expect(address()).toHaveValue("two.example");
});

test("a file chooser answer that is not sent keeps the prompt", () => {
  const toastError = jest.spyOn(toast, "error");
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({ type: "tabs", tabs: [TAB], selected: "t1" });
    socket().receive({ type: "control", controller: "you" });
    socket().receive({ type: "fileChooser", id: "f1", multiple: false });
  });
  socket().readyState = 0;
  act(() => screen.getByRole("button", { name: "Cancel" }).click());
  expect(screen.getByText("The page asks for a file.")).toBeInTheDocument();
  expect(toastError).toHaveBeenCalledWith(
    "Could not answer the page. Try again."
  );
});

test("a page dialog takes focus and gives it back to the page", () => {
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({ type: "tabs", tabs: [TAB], selected: "t1" });
    socket().receive({ type: "control", controller: "you" });
  });
  act(() =>
    socket().receive({
      type: "tabs",
      tabs: [{ ...TAB, dialog: { type: "confirm", message: "Sure?" } }],
      selected: "t1",
    })
  );
  expect(screen.getByRole("button", { name: "Accept" })).toHaveFocus();
  act(() => socket().receive({ type: "tabs", tabs: [TAB], selected: "t1" }));
  expect(screen.getByRole("textbox", { name: "Browser page" })).toHaveFocus();
});

test("a shortcut sent to the page does not run in the app", () => {
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({ type: "tabs", tabs: [TAB], selected: "t1" });
    socket().receive({ type: "control", controller: "you" });
  });
  const input = screen.getByRole("textbox", { name: "Browser page" });
  expect(
    fireEvent.keyDown(input, { key: "r", code: "KeyR", ctrlKey: true })
  ).toBe(false);
  expect(socket().sent.at(-1)).toMatchObject({ type: "key", key: "r" });
  // Paste stays native, so the clipboard's text arrives through onPaste
  expect(
    fireEvent.keyDown(input, { key: "v", code: "KeyV", ctrlKey: true })
  ).toBe(true);
});

test("an AltGr key types its character on the page", () => {
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({ type: "tabs", tabs: [TAB], selected: "t1" });
    socket().receive({ type: "control", controller: "you" });
  });
  const input = screen.getByRole("textbox", { name: "Browser page" });
  // Windows reports AltGr+Q on a German layout as Ctrl+Alt+"@"
  fireEvent.keyDown(input, {
    key: "@",
    code: "KeyQ",
    ctrlKey: true,
    altKey: true,
    modifierAltGraph: true,
  });
  expect(socket().sent.at(-1)).toMatchObject({
    type: "key",
    action: "down",
    key: "@",
    text: "@",
    modifiers: 0,
  });
});

test("another selected tab hides the old page until its own frame comes", async () => {
  const clearRect = jest.fn();
  jest.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    drawImage: () => undefined,
    clearRect,
  } as unknown as CanvasRenderingContext2D);
  Object.defineProperty(globalThis, "createImageBitmap", {
    configurable: true,
    writable: true,
    value: async () => ({ width: 2, height: 2, close: () => undefined }),
  });
  const { container } = renderPanel();
  const canvas = () => container.querySelector("canvas");
  const frame = () =>
    socket().dispatchEvent(
      Object.assign(new Event("message"), { data: new ArrayBuffer(1) })
    );
  const tabs = [TAB, { ...TAB, id: "t2" }];
  act(() => {
    socket().open();
    socket().receive({ type: "tabs", tabs, selected: "t1" });
  });
  await act(async () => frame());
  expect(canvas()).not.toHaveClass("invisible");
  // The same selection keeps the frame
  act(() => socket().receive({ type: "tabs", tabs, selected: "t1" }));
  expect(canvas()).not.toHaveClass("invisible");
  act(() => socket().receive({ type: "tabs", tabs, selected: "t2" }));
  expect(canvas()).toHaveClass("invisible");
  expect(clearRect).toHaveBeenCalled();
  await act(async () => frame());
  expect(canvas()).not.toHaveClass("invisible");
});

// jsdom has no PointerEvent, so pointer fields would not reach the handlers
class TestPointerEvent extends MouseEvent {
  readonly pointerId: number;
  readonly pointerType: string;
  readonly isPrimary: boolean;
  constructor(type: string, init: PointerEventInit = {}) {
    super(type, init);
    this.pointerId = init.pointerId ?? 0;
    this.pointerType = init.pointerType ?? "mouse";
    this.isPrimary = init.isPrimary ?? false;
  }
}
if (typeof globalThis.PointerEvent === "undefined")
  Object.defineProperty(globalThis, "PointerEvent", {
    configurable: true,
    writable: true,
    value: TestPointerEvent,
  });

/** Frames of `width` x `height`; call before the panel renders. */
function mockFrames(width = 400, height = 300) {
  jest.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    drawImage: () => undefined,
    clearRect: () => undefined,
  } as unknown as CanvasRenderingContext2D);
  Object.defineProperty(globalThis, "createImageBitmap", {
    configurable: true,
    writable: true,
    value: async () => ({ width, height, close: () => undefined }),
  });
}

/** Paints a frame on the canvas, laid out at 400x300. */
async function paintFrame(container: HTMLElement) {
  const canvas = container.querySelector("canvas")!;
  jest.spyOn(canvas, "getBoundingClientRect").mockReturnValue({
    left: 0,
    top: 0,
    width: 400,
    height: 300,
  } as DOMRect);
  Object.assign(canvas, { setPointerCapture: () => undefined });
  await act(async () =>
    socket().dispatchEvent(
      Object.assign(new Event("message"), { data: new ArrayBuffer(1) })
    )
  );
  return canvas;
}

const mouseSent = () =>
  socket().sent.filter(
    (message) => (message as { type: string }).type === "mouse"
  );

test("a dialog and a file chooser name the origin that asks", () => {
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({
      type: "tabs",
      tabs: [
        {
          ...TAB,
          dialog: {
            type: "alert",
            message: "Hello",
            origin: "https://example.com",
          },
        },
      ],
      selected: "t1",
    });
    socket().receive({ type: "control", controller: "you" });
    socket().receive({
      type: "fileChooser",
      id: "f1",
      multiple: true,
      origin: "http://plain.example",
    });
  });
  expect(screen.getByText("example.com says")).toBeInTheDocument();
  expect(
    screen.getByText("http://plain.example asks for files.")
  ).toBeInTheDocument();
});

test("a dialog without an origin shows only its message", () => {
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({
      type: "tabs",
      tabs: [{ ...TAB, dialog: { type: "alert", message: "Hello" } }],
      selected: "t1",
    });
  });
  expect(screen.getByRole("dialog", { name: "Page dialog" })).toHaveTextContent(
    /^HelloTake control to respond\.$/
  );
});

test("a blank page shows its dialog", () => {
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({
      type: "tabs",
      tabs: [
        {
          ...TAB,
          url: "about:blank",
          title: "",
          dialog: { type: "alert", message: "Blank says hi" },
        },
      ],
      selected: "t1",
    });
  });
  expect(screen.getByText("Blank says hi")).toBeInTheDocument();
  expect(screen.queryByText("No page yet")).not.toBeInTheDocument();
});

test("a dialog answer that is not sent says so", () => {
  const toastError = jest.spyOn(toast, "error");
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({
      type: "tabs",
      tabs: [{ ...TAB, dialog: { type: "confirm", message: "Sure?" } }],
      selected: "t1",
    });
    socket().receive({ type: "control", controller: "you" });
  });
  socket().readyState = 0;
  act(() => screen.getByRole("button", { name: "Accept" }).click());
  expect(toastError).toHaveBeenCalledWith(
    "Could not answer the page. Try again."
  );
  expect(screen.getByText("Sure?")).toBeInTheDocument();
});

test("a file chooser takes focus and gives it back to the page", () => {
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({ type: "tabs", tabs: [TAB], selected: "t1" });
    socket().receive({ type: "control", controller: "you" });
  });
  const page = screen.getByRole("textbox", { name: "Browser page" });
  act(() => page.focus());
  act(() =>
    socket().receive({ type: "fileChooser", id: "f1", multiple: false })
  );
  expect(screen.getByRole("button", { name: "Choose file" })).toHaveFocus();
  act(() => socket().receive({ type: "fileChooserClosed", id: "f1" }));
  expect(page).toHaveFocus();
});

test("a closed dialog leaves the focus where the user moved it", () => {
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({
      type: "tabs",
      tabs: [{ ...TAB, dialog: { type: "confirm", message: "Sure?" } }],
      selected: "t1",
    });
    socket().receive({ type: "control", controller: "you" });
  });
  const address = screen.getByRole("textbox", { name: "Address" });
  act(() => address.focus());
  act(() => socket().receive({ type: "tabs", tabs: [TAB], selected: "t1" }));
  expect(address).toHaveFocus();
});

test("an upload that fails after its file chooser closed shows no error", async () => {
  const toastError = jest.spyOn(toast, "error");
  jest.spyOn(console, "error").mockImplementation(() => undefined);
  let failUpload: (error: Error) => void = () => undefined;
  jest.mocked(uploadBrowserFiles).mockReturnValue(
    new Promise((_resolve, reject) => {
      failUpload = reject;
    })
  );
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({ type: "tabs", tabs: [TAB], selected: "t1" });
    socket().receive({ type: "control", controller: "you" });
    socket().receive({ type: "fileChooser", id: "f1", multiple: false });
  });
  await userEvent.upload(
    screen.getByLabelText("Files for the page"),
    new File(["a"], "a.txt")
  );
  await waitFor(() => expect(uploadBrowserFiles).toHaveBeenCalled());
  act(() => socket().receive({ type: "fileChooserClosed", id: "f1" }));
  await act(async () => failUpload(new Error("gone")));
  expect(toastError).not.toHaveBeenCalled();
});

test("a key released after a modifier went down still goes up on the page", () => {
  renderPanel();
  act(() => {
    socket().open();
    socket().receive({ type: "tabs", tabs: [TAB], selected: "t1" });
    socket().receive({ type: "control", controller: "you" });
  });
  const input = screen.getByRole("textbox", { name: "Browser page" });
  fireEvent.keyDown(input, { key: "v", code: "KeyV" });
  fireEvent.keyDown(input, {
    key: "Control",
    code: "ControlLeft",
    ctrlKey: true,
  });
  fireEvent.keyUp(input, { key: "v", code: "KeyV", ctrlKey: true });
  expect(socket().sent.at(-1)).toMatchObject({
    type: "key",
    action: "up",
    code: "KeyV",
  });
  // A paste's V went to no page, so its release does not either
  const sent = socket().sent.length;
  fireEvent.keyDown(input, { key: "v", code: "KeyV", ctrlKey: true });
  fireEvent.keyUp(input, { key: "v", code: "KeyV", ctrlKey: true });
  expect(socket().sent).toHaveLength(sent);
});

test("a page switch forgets the old page's clicks, held buttons and touch", async () => {
  mockFrames();
  const { container } = renderPanel();
  const tabs = [TAB, { ...TAB, id: "t2" }];
  act(() => {
    socket().open();
    socket().receive({ type: "tabs", tabs, selected: "t1" });
    socket().receive({ type: "viewport", width: 400, height: 300 });
    socket().receive({ type: "control", controller: "you" });
  });
  const canvas = await paintFrame(container);
  const at = { clientX: 10, clientY: 10, pointerId: 1, pointerType: "mouse" };
  const finger = { ...at, pointerId: 2, pointerType: "touch", isPrimary: true };
  fireEvent.pointerDown(canvas, { ...at, button: 0, buttons: 1 });
  fireEvent.pointerUp(canvas, { ...at, button: 0, buttons: 0 });
  expect(mouseSent()).toMatchObject([
    { action: "down", clickCount: 1 },
    { action: "up" },
  ]);
  // A held button and a finger on page A
  fireEvent.pointerDown(canvas, { ...at, button: 0, buttons: 1 });
  fireEvent.pointerDown(canvas, { ...finger, button: 0, buttons: 1 });
  act(() => socket().receive({ type: "tabs", tabs, selected: "t2" }));
  await paintFrame(container);
  socket().sent = [];
  fireEvent.pointerUp(canvas, { ...at, button: 0, buttons: 0 });
  fireEvent.pointerUp(canvas, { ...finger, button: 0, buttons: 0 });
  expect(mouseSent()).toEqual([]);
  fireEvent.pointerDown(canvas, { ...at, button: 0, buttons: 1 });
  expect(mouseSent().at(-1)).toMatchObject({ action: "down", clickCount: 1 });
});

test("a touch that starts outside the page clicks nothing", async () => {
  mockFrames(400, 200);
  const { container } = renderPanel();
  act(() => {
    socket().open();
    socket().receive({ type: "tabs", tabs: [TAB], selected: "t1" });
    socket().receive({ type: "viewport", width: 400, height: 200 });
    socket().receive({ type: "control", controller: "you" });
  });
  // A 400x200 frame in a 400x300 canvas leaves 50px bands above and below
  const canvas = await paintFrame(container);
  const touch = { pointerId: 1, pointerType: "touch", isPrimary: true };
  fireEvent.pointerDown(canvas, { ...touch, clientX: 200, clientY: 46 });
  fireEvent.pointerUp(canvas, { ...touch, clientX: 200, clientY: 52 });
  expect(mouseSent()).toEqual([]);
});

test("the agent's cursor follows the canvas's size", async () => {
  let width = 400;
  jest
    .spyOn(HTMLElement.prototype, "clientWidth", "get")
    .mockImplementation(() => width);
  jest.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(300);
  const observers: (() => void)[] = [];
  const originalObserver = globalThis.ResizeObserver;
  globalThis.ResizeObserver = class {
    constructor(callback: () => void) {
      observers.push(callback);
    }
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  try {
    mockFrames();
    const { container } = renderPanel();
    const cursor = () =>
      container.querySelector<HTMLElement>("[data-agent-browser-cursor]");
    act(() => {
      socket().open();
      socket().receive({ type: "tabs", tabs: [TAB], selected: "t1" });
      socket().receive({ type: "viewport", width: 400, height: 300 });
      socket().receive({
        type: "pointer",
        phase: "move",
        x: 200,
        y: 0,
        sequence: 1,
      });
    });
    await paintFrame(container);
    expect(cursor()?.style.transform).toBe("translate3d(200px, 0px, 0)");
    width = 200;
    act(() => observers.forEach((notify) => notify()));
    expect(cursor()?.style.transform).toBe("translate3d(100px, 75px, 0)");
  } finally {
    globalThis.ResizeObserver = originalObserver;
  }
});
