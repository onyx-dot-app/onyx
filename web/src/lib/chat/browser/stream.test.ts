import {
  agentCursorPosition,
  browserModifiers,
  browserOriginLabel,
  browserPageTitle,
  browserStreamUrl,
  browserUrlFromInput,
  createBrowserStreamClient,
  isBlankBrowserPage,
  isBrowserOpenStart,
  nextClick,
  pagePointFromClient,
  parseBrowserServerMessage,
  reconnectDelayMs,
  splitBrowserText,
  wheelDeltaUnit,
  type BrowserSocketState,
} from "@/lib/chat/browser/stream";
import type { BrowserServerMessage } from "@/lib/chat/browser/types";

const TAB = {
  id: "t1",
  url: "https://example.com/",
  title: "Example",
  loading: false,
  dialog: null,
};

describe("parseBrowserServerMessage", () => {
  test("reads each known message", () => {
    const cases: [object, BrowserServerMessage][] = [
      [{ type: "starting" }, { type: "starting" }],
      [
        { type: "tabs", tabs: [TAB], selected: "t1" },
        { type: "tabs", tabs: [TAB], selected: "t1" },
      ],
      [
        { type: "viewport", width: 1280, height: 800 },
        { type: "viewport", width: 1280, height: 800 },
      ],
      [
        { type: "control", controller: "another-viewer" },
        { type: "control", controller: "another-viewer" },
      ],
      [
        { type: "pointer", phase: "click", x: 3, y: 4, sequence: 9 },
        { type: "pointer", phase: "click", x: 3, y: 4, sequence: 9 },
      ],
      [
        { type: "fileChooser", id: "f1", multiple: true, accept: ".pdf" },
        { type: "fileChooser", id: "f1", multiple: true, origin: null },
      ],
      [
        {
          type: "fileChooser",
          id: "f2",
          multiple: false,
          origin: "https://example.com",
        },
        {
          type: "fileChooser",
          id: "f2",
          multiple: false,
          origin: "https://example.com",
        },
      ],
      [
        { type: "fileChooserClosed", id: "f1" },
        { type: "fileChooserClosed", id: "f1" },
      ],
      [
        {
          type: "download",
          fileName: "a.csv",
          path: "downloads/a.csv",
          sizeBytes: 12,
        },
        { type: "download", fileName: "a.csv" },
      ],
      [
        { type: "error", message: "No control" },
        { type: "error", message: "No control" },
      ],
    ];
    for (const [input, expected] of cases)
      expect(parseBrowserServerMessage(JSON.stringify(input))).toEqual(
        expected
      );
  });

  test("drops malformed tabs and keeps the rest", () => {
    const message = parseBrowserServerMessage(
      JSON.stringify({
        type: "tabs",
        tabs: [TAB, { id: 3 }, { ...TAB, id: "t2", loading: "yes" }],
        selected: null,
      })
    );
    expect(message).toEqual({ type: "tabs", tabs: [TAB], selected: null });
  });

  test("reads a tab's dialog and its origin, null when unknown", () => {
    const dialog = {
      type: "prompt",
      message: "Name?",
      origin: "http://example.com",
    };
    const message = parseBrowserServerMessage(
      JSON.stringify({
        type: "tabs",
        tabs: [
          { ...TAB, dialog },
          { ...TAB, id: "t2", dialog: { type: "alert", message: "Hi" } },
        ],
        selected: "t1",
      })
    );
    expect(message).toEqual({
      type: "tabs",
      tabs: [
        { ...TAB, dialog },
        {
          ...TAB,
          id: "t2",
          dialog: { type: "alert", message: "Hi", origin: null },
        },
      ],
      selected: "t1",
    });
  });

  test("names an https origin by its host and any other in full", () => {
    expect(browserOriginLabel("https://example.com")).toBe("example.com");
    expect(browserOriginLabel("https://example.com:8443")).toBe(
      "example.com:8443"
    );
    expect(browserOriginLabel("http://example.com")).toBe("http://example.com");
  });

  test("gives null for unknown or broken messages", () => {
    for (const data of [
      "not json",
      "[]",
      "null",
      JSON.stringify({ type: "mystery" }),
      JSON.stringify({ type: "viewport", width: "1" }),
      JSON.stringify({ type: "control", controller: "robot" }),
      JSON.stringify({
        type: "pointer",
        phase: "drag",
        x: 1,
        y: 1,
        sequence: 1,
      }),
      JSON.stringify({ type: "tabs", tabs: "t1" }),
    ])
      expect(parseBrowserServerMessage(data)).toBeNull();
  });
});

describe("pagePointFromClient", () => {
  // A 400x400 canvas at (100, 50) showing a 200x100 frame of a 1000x500 page:
  // the frame fills the width, 200 px tall, centered with 100 px above
  const rect = { left: 100, top: 50, width: 400, height: 400 };
  const frame = { width: 200, height: 100 };
  const viewport = { width: 1000, height: 500 };

  test("maps a point inside the contained frame to the page", () => {
    expect(pagePointFromClient(300, 250, rect, frame, viewport, false)).toEqual(
      { x: 500, y: 250, scale: 2.5 }
    );
    expect(pagePointFromClient(100, 150, rect, frame, viewport, false)).toEqual(
      { x: 0, y: 0, scale: 2.5 }
    );
  });

  test("gives null in the letterbox unless it clamps", () => {
    expect(pagePointFromClient(300, 100, rect, frame, viewport, false)).toBe(
      null
    );
    expect(pagePointFromClient(300, 100, rect, frame, viewport, true)).toEqual({
      x: 500,
      y: 0,
      scale: 2.5,
    });
    expect(pagePointFromClient(900, 900, rect, frame, viewport, true)).toEqual({
      x: 1000,
      y: 500,
      scale: 2.5,
    });
  });

  test("gives null without a frame", () => {
    expect(
      pagePointFromClient(
        300,
        250,
        rect,
        { width: 0, height: 0 },
        viewport,
        true
      )
    ).toBeNull();
  });
});

describe("agent cursor", () => {
  test("places the page point in the contained frame", () => {
    const box = { width: 400, height: 400 };
    const frame = { width: 200, height: 100 };
    const viewport = { width: 1000, height: 500 };
    expect(
      agentCursorPosition({ x: 500, y: 250 }, box, frame, viewport)
    ).toEqual({ left: 200, top: 200 });
    expect(agentCursorPosition({ x: 0, y: 0 }, box, frame, viewport)).toEqual({
      left: 0,
      top: 100,
    });
    expect(
      agentCursorPosition({ x: 0, y: 0 }, box, frame, { width: 0, height: 0 })
    ).toBeNull();
  });
});

describe("splitBrowserText", () => {
  test("keeps short text whole and splits long text in order", () => {
    expect(splitBrowserText("abc")).toEqual(["abc"]);
    const long = "a".repeat(10_000) + "b".repeat(10_000) + "c";
    expect(splitBrowserText(long)).toEqual([
      "a".repeat(10_000),
      "b".repeat(10_000),
      "c",
    ]);
  });

  test("does not split a surrogate pair", () => {
    const text = "a".repeat(9_999) + "\u{1F600}" + "b";
    const chunks = splitBrowserText(text);
    expect(chunks).toEqual(["a".repeat(9_999), "\u{1F600}b"]);
    expect(chunks.join("")).toBe(text);
  });
});

describe("input helpers", () => {
  test("the modifier bitmask follows the contract", () => {
    const none = {
      altKey: false,
      ctrlKey: false,
      metaKey: false,
      shiftKey: false,
    };
    expect(browserModifiers(none)).toBe(0);
    expect(browserModifiers({ ...none, altKey: true })).toBe(1);
    expect(browserModifiers({ ...none, ctrlKey: true })).toBe(2);
    expect(browserModifiers({ ...none, metaKey: true })).toBe(4);
    expect(browserModifiers({ ...none, shiftKey: true })).toBe(8);
    expect(
      browserModifiers({
        altKey: true,
        ctrlKey: true,
        metaKey: true,
        shiftKey: true,
      })
    ).toBe(15);
  });

  test("counts quick, near presses of one button as one multi-click", () => {
    let click = nextClick(null, "left", 0, 10, 10);
    expect(click.count).toBe(1);
    click = nextClick(click, "left", 200, 11, 11);
    expect(click.count).toBe(2);
    click = nextClick(click, "left", 400, 11, 11);
    expect(click.count).toBe(3);
    expect(nextClick(click, "right", 450, 11, 11).count).toBe(1);
    expect(nextClick(click, "left", 1000, 11, 11).count).toBe(1);
    expect(nextClick(click, "left", 450, 30, 11).count).toBe(1);
  });

  test("wheel lines are 16 px and pages the viewport", () => {
    expect(wheelDeltaUnit(0, 800)).toBe(1);
    expect(wheelDeltaUnit(1, 800)).toBe(16);
    expect(wheelDeltaUnit(2, 800)).toBe(800);
  });

  test("reconnects wait twice as long each time, up to 10 s", () => {
    expect([0, 1, 2, 3, 4, 5].map(reconnectDelayMs)).toEqual([
      500, 1000, 2000, 4000, 8000, 10000,
    ]);
  });

  test("the URL bar sends its trimmed text and leaves the scheme to the service", () => {
    expect(browserUrlFromInput(" example.com/a ")).toBe("example.com/a");
    expect(browserUrlFromInput("http://example.com")).toBe(
      "http://example.com"
    );
    expect(browserUrlFromInput("   ")).toBeNull();
  });

  test("the websocket URL is on the page's origin", () => {
    expect(
      browserStreamUrl("abc", { protocol: "https:", host: "onyx.example" })
    ).toBe("wss://onyx.example/api/chat/sessions/abc/browser/ws");
    expect(
      browserStreamUrl("abc", { protocol: "http:", host: "localhost:3000" })
    ).toBe("ws://localhost:3000/api/chat/sessions/abc/browser/ws");
  });

  test("only a browser_open tool start opens the panel", () => {
    expect(
      isBrowserOpenStart({
        type: "custom_tool_start",
        tool_name: "browser_open",
      })
    ).toBe(true);
    expect(
      isBrowserOpenStart({
        type: "custom_tool_start",
        tool_name: "browser_act",
      })
    ).toBe(false);
    expect(isBrowserOpenStart({ type: "message_start" })).toBe(false);
  });
});

/** A socket the test drives by hand. */
class FakeSocket extends EventTarget {
  static OPEN = 1;
  readyState = 0;
  binaryType = "blob";
  sent: string[] = [];
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.closeWith(1000);
  }
  open() {
    this.readyState = 1;
    this.dispatchEvent(new Event("open"));
  }
  receive(data: string | ArrayBuffer) {
    this.dispatchEvent(Object.assign(new Event("message"), { data }));
  }
  closeWith(code: number) {
    if (this.readyState === 3) return;
    this.readyState = 3;
    this.dispatchEvent(Object.assign(new Event("close"), { code }));
  }
}

describe("createBrowserStreamClient", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  function start() {
    const sockets: FakeSocket[] = [];
    const states: BrowserSocketState[] = [];
    const messages: BrowserServerMessage[] = [];
    const frames: ArrayBuffer[] = [];
    const urls: string[] = [];
    const client = createBrowserStreamClient({
      url: "ws://test/ws",
      events: {
        onState: (state) => states.push(state),
        onMessage: (message) => messages.push(message),
        onFrame: (jpeg) => frames.push(jpeg),
      },
      createSocket: (url) => {
        urls.push(url);
        const socket = new FakeSocket();
        sockets.push(socket);
        // SAFETY: FakeSocket implements the members the client uses
        return socket as unknown as WebSocket;
      },
    });
    return {
      client,
      sockets,
      states,
      messages,
      frames,
      urls,
    };
  }

  test("sends nothing on open and acks each frame on receipt", () => {
    const { sockets, states, frames, messages } = start();
    const socket = sockets[0];
    if (!socket) throw new Error("no socket");
    socket.open();
    expect(socket.sent).toEqual([]);
    expect(states).toEqual(["connecting"]);

    socket.receive(new ArrayBuffer(3));
    expect(frames).toHaveLength(1);
    expect(socket.sent[0]).toBe(JSON.stringify({ type: "ack" }));

    socket.receive(JSON.stringify({ type: "starting" }));
    socket.receive("garbage");
    expect(messages).toEqual([{ type: "starting" }]);
  });

  test("reconnects after a drop", () => {
    const { sockets, states, urls } = start();
    sockets[0]?.open();
    sockets[0]?.closeWith(1006);
    expect(states.at(-1)).toBe("disconnected");
    jest.advanceTimersByTime(499);
    expect(sockets).toHaveLength(1);
    jest.advanceTimersByTime(1);
    expect(sockets).toHaveLength(2);
    expect(urls).toEqual(["ws://test/ws", "ws://test/ws"]);
  });

  test("stops on a forbidden or unavailable close", () => {
    const forbidden = start();
    forbidden.sockets[0]?.closeWith(4403);
    expect(forbidden.states.at(-1)).toBe("disabled");
    jest.advanceTimersByTime(20_000);
    expect(forbidden.sockets).toHaveLength(1);

    const unavailable = start();
    unavailable.sockets[0]?.closeWith(4503);
    expect(unavailable.states.at(-1)).toBe("error");
    jest.advanceTimersByTime(20_000);
    expect(unavailable.sockets).toHaveLength(1);
  });

  test("stops after connects that never open, until one opens", () => {
    const { sockets, states } = start();
    for (let i = 0; i < 5; i++) {
      sockets.at(-1)?.closeWith(1006);
      jest.advanceTimersByTime(10_000);
    }
    expect(sockets).toHaveLength(6);
    // An open connect starts the count again
    sockets.at(-1)?.open();
    sockets.at(-1)?.closeWith(1006);
    for (let i = 0; i < 6; i++) {
      jest.advanceTimersByTime(10_000);
      sockets.at(-1)?.closeWith(1006);
    }
    expect(sockets).toHaveLength(12);
    expect(states.at(-1)).toBe("unreachable");
    jest.advanceTimersByTime(20_000);
    expect(sockets).toHaveLength(12);
  });

  test("stop closes the socket and sends no more", () => {
    const { client, sockets, states } = start();
    sockets[0]?.open();
    client.stop();
    expect(client.send({ type: "takeControl" })).toBe(false);
    jest.advanceTimersByTime(20_000);
    expect(sockets).toHaveLength(1);
    expect(states).toEqual(["connecting"]);
  });
});

describe("browser page tabs", () => {
  test("a page's tab shows its title, else its URL's host, as T3 Code's", () => {
    expect(browserPageTitle(TAB)).toBe("Example");
    expect(
      browserPageTitle({ title: "  ", url: "https://docs.example.org/a?b" })
    ).toBe("docs.example.org");
    expect(browserPageTitle({ title: "", url: "about:blank" })).toBeNull();
    expect(browserPageTitle({ title: "", url: "" })).toBeNull();
    expect(browserPageTitle({ title: "invoice\u202Efdp.exe", url: "" })).toBe(
      "invoicefdp.exe"
    );
  });

  test("a page is blank until it loads its first URL", () => {
    const blank = { url: "about:blank", loading: false, title: "" };
    expect(isBlankBrowserPage(blank)).toBe(true);
    expect(isBlankBrowserPage({ ...blank, url: "" })).toBe(true);
    expect(isBlankBrowserPage({ ...blank, loading: true })).toBe(false);
    expect(isBlankBrowserPage(TAB)).toBe(false);
  });

  test("a blank page that the opener wrote a title into is not blank", () => {
    expect(
      isBlankBrowserPage({ url: "about:blank", loading: false, title: "Print" })
    ).toBe(false);
  });
});
