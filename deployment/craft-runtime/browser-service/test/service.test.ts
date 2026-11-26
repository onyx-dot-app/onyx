import * as assert from "node:assert/strict";
import * as NodeCrypto from "node:crypto";
import * as NodeFSP from "node:fs/promises";
import * as NodeOS from "node:os";
import * as NodePath from "node:path";
import { after, before, describe, test } from "node:test";
import { encodeJson, FrameDecoder, MAX_FRAME_LENGTH } from "../src/framing.ts";
import { HUMAN_CONTROL_MESSAGE } from "../src/errors.ts";
import { normalizeUrl } from "../src/paths.ts";
import {
  call,
  launchChrome,
  ok,
  rawSocket,
  startService,
  startSite,
  ViewerClient,
  waitUntil,
} from "./helpers.ts";
import type { Chrome, Service, Site } from "./helpers.ts";

type TabJson = { id: string; url: string; title: string; controller: string };

const newChat = () => NodeCrypto.randomUUID();

const refFor = (text: string, label: string) => {
  const line = text.split("\n").find((each) => each.includes(label) && each.includes("[ref="));
  const ref = line ? /\[ref=([^\]]+)\]/.exec(line)?.[1] : undefined;
  assert.ok(ref, `no ref for ${label} in:\n${text}`);
  return ref;
};

const boxOf = async (socketPath: string, chat: string, selector: string) => {
  const result = await ok(socketPath, chat, "evaluate", {
    expression: `(() => { const r = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect(); return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; })()`,
  });
  return result.value as { x: number; y: number };
};

const clickAt = (viewer: ViewerClient, x: number, y: number) => {
  viewer.send({ type: "mouse", action: "move", x, y, button: "none", buttons: 0, clickCount: 0, modifiers: 0 });
  viewer.send({ type: "mouse", action: "down", x, y, button: "left", buttons: 1, clickCount: 1, modifiers: 0 });
  viewer.send({ type: "mouse", action: "up", x, y, button: "left", buttons: 0, clickCount: 1, modifiers: 0 });
};

describe("framing", () => {
  test("decoder splits frames", () => {
    const decoder = new FrameDecoder();
    const bytes = Buffer.concat([encodeJson({ a: 1 }), encodeJson({ b: 2 })]);
    assert.deepEqual(
      [...decoder.push(bytes.subarray(0, 7)), ...decoder.push(bytes.subarray(7))].map((m) =>
        m.kind === 1 ? m.value : null,
      ),
      [{ a: 1 }, { b: 2 }],
    );
  });
});

describe("normalizeUrl", () => {
  test("adds a scheme to bare hosts", () => {
    assert.equal(normalizeUrl("  localhost:3000 "), "http://localhost:3000/");
    assert.equal(normalizeUrl("127.0.0.1:8080/x"), "http://127.0.0.1:8080/x");
    assert.equal(normalizeUrl("example.com"), "https://example.com/");
    assert.equal(normalizeUrl("example.com:8443/a"), "https://example.com:8443/a");
    assert.equal(normalizeUrl("http://example.com/a"), "http://example.com/a");
    assert.equal(normalizeUrl("about:blank"), "about:blank");
  });

  test("rejects other schemes", () => {
    for (const url of ["data:text/html,hi", "javascript:alert(1)", "file:///etc/passwd", "mailto:a:b@example.com", ""])
      assert.throws(() => normalizeUrl(url), (error: Error & { code?: string }) => error.code === "invalid_argument");
  });
});

describe("browser service", () => {
  let chrome: Chrome;
  let service: Service;
  let site: Site;
  const cleanups: Array<() => Promise<void>> = [];

  before(async () => {
    chrome = await launchChrome();
    cleanups.unshift(() => chrome.stop());
    service = await startService(chrome.cdpUrl);
    cleanups.unshift(() => service.stop());
    site = await startSite();
    cleanups.unshift(() => site.stop());
  });

  after(async () => {
    const errors: Array<unknown> = [];
    for (const cleanup of cleanups) await cleanup().catch((error: unknown) => errors.push(error));
    if (errors.length > 0) throw errors[0];
  });

  test("server closes a connection that sends an oversize length", async () => {
    const socket = await rawSocket(service.socketPath);
    const header = Buffer.alloc(5);
    header.writeUInt32BE(MAX_FRAME_LENGTH + 1, 0);
    header.writeUInt8(1, 4);
    const received: Array<Buffer> = [];
    socket.on("data", (chunk: Buffer) => received.push(chunk));
    const closed = new Promise((resolve) => socket.on("close", resolve));
    socket.write(header);
    await closed;
    assert.equal(Buffer.concat(received).length, 0);
    // The service still answers other connections.
    const reply = await call(service.socketPath, newChat(), "status");
    assert.equal(reply.ok, true);
  });

  test("a call client that half-closes still gets its reply", async () => {
    const socket = await rawSocket(service.socketPath);
    const decoder = new FrameDecoder();
    const replies: Array<Record<string, unknown>> = [];
    socket.on("data", (chunk: Buffer) => {
      for (const message of decoder.push(chunk)) if (message.kind === 1) replies.push(message.value);
    });
    const closed = new Promise((resolve) => socket.on("close", resolve));
    socket.end(encodeJson({ op: "call", chat: newChat(), method: "status", params: {} }));
    await closed;
    assert.deepEqual(replies, [{ ok: true, result: { tabs: [], current: null } }]);
  });

  test("agent opens, snapshots, clicks and types with refs", async () => {
    const chat = newChat();
    const missing = await call(service.socketPath, chat, "snapshot");
    assert.equal(missing.ok, false);
    if (!missing.ok) assert.equal(missing.error.code, "tab_required");

    const opened = await ok(service.socketPath, chat, "open", { url: `${site.url}/form` });
    const tab = opened.tab as TabJson;
    assert.match(tab.id, /^t\d+$/);
    assert.equal(tab.title, "Form page");
    assert.equal(tab.controller, "agent");

    const snap = await ok(service.socketPath, chat, "snapshot");
    const text = snap.text as string;
    assert.match(text, /^Title: Form page\nURL: http:\/\/127\.0\.0\.1:\d+\/form\n/);
    const button = refFor(text, 'button "Press me"');
    assert.match(button, /^e[0-9a-z]+_\d+$/);

    await ok(service.socketPath, chat, "act", { action: "click", ref: button });
    await ok(service.socketPath, chat, "waitFor", { text: "clicked 1" });

    const input = refFor(text, "textbox");
    await ok(service.socketPath, chat, "act", { action: "type", ref: input, text: "Ada" });
    const value = await ok(service.socketPath, chat, "evaluate", {
      expression: "document.getElementById('name').value",
    });
    assert.equal(value.value, "Ada");

    const screenshot = await ok(service.socketPath, chat, "snapshot", { screenshotPath: "shots/page.png" });
    assert.ok(screenshot.text);
    const png = await NodeFSP.readFile(NodePath.join(service.sessionsRoot, chat, "shots", "page.png"));
    assert.equal(png.subarray(1, 4).toString(), "PNG");

    const escape = await call(service.socketPath, chat, "snapshot", { screenshotPath: "../x.png" });
    assert.equal(escape.ok, false);
    if (!escape.ok) assert.equal(escape.error.code, "invalid_argument");
  });

  test("a ref from an older snapshot is stale", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/form` });
    const first = (await ok(service.socketPath, chat, "snapshot")).text as string;
    const old = refFor(first, 'button "Press me"');
    await ok(service.socketPath, chat, "snapshot");
    const reply = await call(service.socketPath, chat, "act", { action: "click", ref: old });
    assert.equal(reply.ok, false);
    if (!reply.ok) assert.equal(reply.error.code, "stale_ref");
  });

  test("a ref survives an iframe that navigates", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/busy-frame` });
    const ref = refFor((await ok(service.socketPath, chat, "snapshot")).text as string, 'button "Go"');
    // The ad frame reloads once after the snapshot
    await new Promise((resolve) => setTimeout(resolve, 600));
    await ok(service.socketPath, chat, "act", { action: "click", ref });
    await ok(service.socketPath, chat, "waitFor", { text: "clicked", timeoutMs: 5_000 });
  });

  test("a ref survives a history rewrite of the page's URL", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/rewrite` });
    const ref = refFor((await ok(service.socketPath, chat, "snapshot")).text as string, 'button "Go"');
    await ok(service.socketPath, chat, "waitFor", { urlIncludes: "ready", timeoutMs: 5_000 });
    await ok(service.socketPath, chat, "act", { action: "click", ref });
    await ok(service.socketPath, chat, "waitFor", { text: "clicked", timeoutMs: 5_000 });
  });

  test("a ref dies when the page loads a new document", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/form` });
    const ref = refFor((await ok(service.socketPath, chat, "snapshot")).text as string, 'button "Press me"');
    await ok(service.socketPath, chat, "navigate", { url: `${site.url}/form` });
    const reply = await call(service.socketPath, chat, "act", { action: "click", ref });
    assert.equal(reply.ok, false);
    if (!reply.ok) assert.equal(reply.error.code, "stale_ref");
  });

  test("human control refuses agent writes until released", async () => {
    const chat = newChat();
    const opened = await ok(service.socketPath, chat, "open", { url: `${site.url}/form` });
    const tabId = (opened.tab as TabJson).id;
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    viewer.autoAck = true;
    try {
      await viewer.message("control", (m) => m.controller === "agent");
      viewer.send({ type: "takeControl" });
      await viewer.message("control", (m) => m.controller === "you");

      const refused = await call(service.socketPath, chat, "act", { action: "click", selector: "#btn" });
      assert.equal(refused.ok, false);
      if (!refused.ok) {
        assert.equal(refused.error.code, "human_control");
        assert.equal(refused.error.message, HUMAN_CONTROL_MESSAGE);
      }
      const reopen = await call(service.socketPath, chat, "open", { url: `${site.url}/second` });
      assert.equal(reopen.ok, false);
      if (!reopen.ok) assert.equal(reopen.error.code, "human_control");

      // Reads still work.
      const snap = await ok(service.socketPath, chat, "snapshot");
      assert.match(snap.text as string, /Press me/);
      const status = await ok(service.socketPath, chat, "status");
      assert.equal((status.tabs as Array<TabJson>)[0]?.controller, "human");

      // A new tab keeps the agent working, and the controlling viewer stays on its tab.
      const other = await ok(service.socketPath, chat, "open", { url: `${site.url}/second`, newTab: true });
      const otherId = (other.tab as TabJson).id;
      assert.notEqual(otherId, tabId);
      await viewer.message("tabs", (m) => (m.tabs as Array<TabJson>).some((tab) => tab.id === otherId));
      assert.equal(viewer.messages.findLast((m) => m.type === "tabs")?.selected, tabId);

      viewer.send({ type: "releaseControl" });
      await viewer.waitFor(() =>
        viewer.messages.findLast((m) => m.type === "control")?.controller !== "you" ? true : undefined,
      );
      await ok(service.socketPath, chat, "act", { tab: tabId, action: "click", selector: "#btn" });
      await ok(service.socketPath, chat, "waitFor", { text: "clicked 1" });
    } finally {
      viewer.close();
    }
  });

  test("a takeover fails queued agent writes, but queued reads still run", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/form` });
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    viewer.autoAck = true;
    try {
      await viewer.message("control", (m) => m.controller === "agent");
      const busy = ok(service.socketPath, chat, "evaluate", {
        expression: "new Promise((resolve) => setTimeout(() => resolve(1), 1500))",
      });
      const read = call(service.socketPath, chat, "snapshot");
      const write = call(service.socketPath, chat, "act", { action: "click", selector: "#btn" });
      // Let both calls reach the tab's queue behind the evaluation.
      await new Promise((resolve) => setTimeout(resolve, 300));
      viewer.send({ type: "takeControl" });
      await viewer.message("control", (m) => m.controller === "you");
      assert.equal((await busy).value, 1);
      const snap = await read;
      assert.ok(snap.ok, JSON.stringify(snap));
      assert.match(snap.result.text as string, /Press me/);
      const refused = await write;
      assert.equal(refused.ok, false);
      if (!refused.ok) {
        assert.equal(refused.error.code, "human_control");
        assert.equal(refused.error.message, HUMAN_CONTROL_MESSAGE);
      }
    } finally {
      viewer.close();
    }
  });

  test("viewers see the agent take over a tab and follow the agent's new tab", async () => {
    const chat = newChat();
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    viewer.autoAck = true;
    try {
      viewer.send({ type: "newTab", url: `${site.url}/form` });
      const tabs = await viewer.message("tabs", (m) => (m.tabs as Array<TabJson>).length === 1);
      const tabId = (tabs.tabs as Array<TabJson>)[0]!.id;
      await viewer.message("control", (m) => m.controller === "you");
      viewer.messages.length = 0;
      viewer.send({ type: "releaseControl" });
      await viewer.message("control", (m) => m.controller === "none");
      viewer.messages.length = 0;
      await ok(service.socketPath, chat, "evaluate", { tab: tabId, expression: "1" });
      await viewer.message("control", (m) => m.controller === "agent");
      await viewer.message("tabs", (m) => (m.tabs as Array<TabJson>)[0]?.controller === "agent");
      const opened = await ok(service.socketPath, chat, "open", { newTab: true });
      const newId = (opened.tab as TabJson).id;
      await viewer.message("tabs", (m) => m.selected === newId);
    } finally {
      viewer.close();
    }
  });

  test("a disconnect releases control", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/form` });
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    try {
      viewer.send({ type: "takeControl" });
      await viewer.message("control", (m) => m.controller === "you");
    } finally {
      viewer.close();
    }
    const deadline = Date.now() + 5_000;
    for (;;) {
      const reply = await call(service.socketPath, chat, "act", { action: "click", selector: "#btn" });
      if (reply.ok) break;
      assert.ok(Date.now() < deadline, "control was not released");
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
  });

  test("two chats see only their own tabs", async () => {
    const chatA = newChat();
    const chatB = newChat();
    const opened = await ok(service.socketPath, chatA, "open", { url: `${site.url}/form` });
    const tabA = (opened.tab as TabJson).id;
    const statusB = await ok(service.socketPath, chatB, "status");
    assert.deepEqual(statusB.tabs, []);
    assert.equal(statusB.current, null);
    const cross = await call(service.socketPath, chatB, "snapshot", { tab: tabA });
    assert.equal(cross.ok, false);
    if (!cross.ok) assert.equal(cross.error.code, "tab_not_found");
    const viewer = await ViewerClient.connect(service.socketPath, chatB);
    try {
      const tabs = await viewer.message("tabs");
      assert.deepEqual(tabs.tabs, []);
      assert.equal(tabs.selected, null);
    } finally {
      viewer.close();
    }
  });

  test("viewer frames wait for acks", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/animated` });
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    try {
      const viewport = await viewer.message("viewport");
      assert.equal(viewport.width, 1280);
      assert.equal(viewport.height, 800);
      await viewer.waitFor(() => viewer.frames.length >= 1);
      const first = viewer.frames[0]!;
      assert.equal(first.readUInt16BE(0), 0xffd8);
      // Without an ack no other frame arrives on an animated page.
      await new Promise((resolve) => setTimeout(resolve, 700));
      assert.equal(viewer.frames.length, 1);
      viewer.send({ type: "ack" });
      await viewer.waitFor(() => viewer.frames.length >= 2);
      viewer.autoAck = true;
      viewer.send({ type: "ack" });
      const start = viewer.frames.length;
      await new Promise((resolve) => setTimeout(resolve, 2_000));
      const count = viewer.frames.length - start;
      assert.ok(count >= 3, `too few frames: ${count}`);
      // 100 ms ack pacing with three frames in Chromium's window caps near 30 fps.
      assert.ok(count <= 70, `ack pacing missing: ${count} frames in 2 s`);
    } finally {
      viewer.close();
    }
  });

  test("viewer input reaches the page and the agent cursor reaches the viewer", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/form` });
    const center = await boxOf(service.socketPath, chat, "#btn");
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    viewer.autoAck = true;
    try {
      await viewer.message("viewport");
      await ok(service.socketPath, chat, "act", { action: "click", selector: "#btn" });
      const move = await viewer.message("pointer", (m) => m.phase === "move");
      const click = await viewer.message("pointer", (m) => m.phase === "click");
      assert.equal(move.x, center.x);
      assert.equal(click.y, center.y);
      assert.ok((click.sequence as number) > (move.sequence as number));

      clickAt(viewer, center.x, center.y);
      await viewer.message("error");
      viewer.messages.length = 0;

      viewer.send({ type: "takeControl" });
      await viewer.message("control", (m) => m.controller === "you");
      clickAt(viewer, center.x, center.y);
      await ok(service.socketPath, chat, "waitFor", { text: "clicked 2", timeoutMs: 5_000 });
      const status = await ok(service.socketPath, chat, "status");
      assert.equal((status.tabs as Array<TabJson>)[0]?.controller, "human");
    } finally {
      viewer.close();
    }
  });

  test("a title that the page sets later reaches the viewer", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/retitle` });
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    viewer.autoAck = true;
    try {
      await viewer.message("tabs", (m) => (m.tabs as Array<TabJson>)[0]?.title === "After");
    } finally {
      viewer.close();
    }
  });

  test("viewer opens a tab, navigates and closes it", async () => {
    const chat = newChat();
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    viewer.autoAck = true;
    try {
      await viewer.message("tabs");
      viewer.send({ type: "newTab", url: `${site.url}/form` });
      const tabs = await viewer.message("tabs", (m) =>
        (m.tabs as Array<TabJson>).some((tab) => tab.title === "Form page"),
      );
      const tab = (tabs.tabs as Array<TabJson>)[0]!;
      assert.equal(tabs.selected, tab.id);
      await viewer.message("control", (m) => m.controller === "you");
      // A second window shows the same tab, though no agent made it current.
      const second = await ViewerClient.connect(service.socketPath, chat);
      second.autoAck = true;
      try {
        await second.message("tabs", (m) => m.selected === tab.id);
        await second.message("control", (m) => m.controller === "another-viewer");
      } finally {
        second.close();
      }
      viewer.send({ type: "navigate", url: `${site.url}/second` });
      await viewer.message("tabs", (m) =>
        (m.tabs as Array<TabJson>).some((each) => each.title === "Second page"),
      );
      viewer.send({ type: "closeTab", tab: tab.id });
      await viewer.message("tabs", (m) => (m.tabs as Array<TabJson>).length === 0 && m.selected === null);
    } finally {
      viewer.close();
    }
  });

  test("the file chooser goes to the controlling viewer", async () => {
    const chat = newChat();
    const uploads = NodePath.join(service.sessionsRoot, chat, "browser-uploads");
    await NodeFSP.mkdir(uploads, { recursive: true });
    await NodeFSP.writeFile(NodePath.join(uploads, "notes.txt"), "hello");
    await ok(service.socketPath, chat, "open", { url: `${site.url}/upload` });
    const center = await boxOf(service.socketPath, chat, "#file");
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    viewer.autoAck = true;
    try {
      viewer.send({ type: "takeControl" });
      await viewer.message("control", (m) => m.controller === "you");
      clickAt(viewer, center.x, center.y);
      const chooser = await viewer.message("fileChooser");
      assert.equal(chooser.multiple, false);
      viewer.send({ type: "fileChooser", id: chooser.id, paths: ["../escape.txt"] });
      await viewer.message("error");
      viewer.send({ type: "fileChooser", id: chooser.id, paths: ["browser-uploads/notes.txt"] });
      await viewer.message("fileChooserClosed", (m) => m.id === chooser.id);
      await ok(service.socketPath, chat, "waitFor", { text: "picked notes.txt", timeoutMs: 5_000 });
    } finally {
      viewer.close();
    }
  });

  test("a file chooser answer sent before a release does not set files", async () => {
    const chat = newChat();
    const uploads = NodePath.join(service.sessionsRoot, chat, "browser-uploads");
    await NodeFSP.mkdir(uploads, { recursive: true });
    await NodeFSP.writeFile(NodePath.join(uploads, "notes.txt"), "hello");
    await ok(service.socketPath, chat, "open", { url: `${site.url}/upload` });
    const center = await boxOf(service.socketPath, chat, "#file");
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    viewer.autoAck = true;
    try {
      viewer.send({ type: "takeControl" });
      await viewer.message("control", (m) => m.controller === "you");
      clickAt(viewer, center.x, center.y);
      const chooser = await viewer.message("fileChooser");
      // The release arrives while the answer's path checks wait on the disk.
      viewer.sendAll([
        { type: "fileChooser", id: chooser.id, paths: ["browser-uploads/notes.txt"] },
        { type: "releaseControl" },
      ]);
      await viewer.message("error");
      const text = await ok(service.socketPath, chat, "evaluate", {
        expression: "document.getElementById('picked').textContent",
      });
      assert.notEqual(text.value, "picked notes.txt");
    } finally {
      viewer.close();
    }
  });

  test("a file chooser closes on a new document but stays on a history rewrite", async () => {
    const chat = newChat();
    const uploads = NodePath.join(service.sessionsRoot, chat, "browser-uploads");
    await NodeFSP.mkdir(uploads, { recursive: true });
    await NodeFSP.writeFile(NodePath.join(uploads, "notes.txt"), "hello");
    await ok(service.socketPath, chat, "open", { url: `${site.url}/upload-rewrite` });
    const center = await boxOf(service.socketPath, chat, "#file");
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    viewer.autoAck = true;
    try {
      viewer.send({ type: "takeControl" });
      await viewer.message("control", (m) => m.controller === "you");
      clickAt(viewer, center.x, center.y);
      const first = await viewer.message("fileChooser");
      await viewer.message("tabs", (m) => (m.tabs as Array<TabJson>)[0]?.url.endsWith("?rewritten") ?? false);
      assert.ok(!viewer.messages.some((m) => m.type === "fileChooserClosed" && m.id === first.id));
      viewer.send({ type: "fileChooser", id: first.id, paths: ["browser-uploads/notes.txt"] });
      await viewer.message("fileChooserClosed", (m) => m.id === first.id);
      await ok(service.socketPath, chat, "waitFor", { text: "picked notes.txt", timeoutMs: 5_000 });

      clickAt(viewer, center.x, center.y);
      const second = await viewer.message("fileChooser", (m) => m.id !== first.id);
      viewer.send({ type: "navigate", url: `${site.url}/upload-rewrite` });
      await viewer.message("fileChooserClosed", (m) => m.id === second.id);
    } finally {
      viewer.close();
    }
  });

  test("agent upload sets files from the chat session dir", async () => {
    const chat = newChat();
    const dir = NodePath.join(service.sessionsRoot, chat);
    await NodeFSP.mkdir(dir, { recursive: true });
    await NodeFSP.writeFile(NodePath.join(dir, "data.csv"), "a,b");
    await ok(service.socketPath, chat, "open", { url: `${site.url}/upload` });
    const result = await ok(service.socketPath, chat, "act", {
      action: "upload",
      selector: "#file",
      paths: ["data.csv"],
    });
    assert.equal(result.message, "Uploaded 1 file.");
    await ok(service.socketPath, chat, "waitFor", { text: "picked data.csv" });
  });

  test("a download lands in the chat's downloads folder", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/download-page` });
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    viewer.autoAck = true;
    try {
      await viewer.message("viewport");
      await ok(service.socketPath, chat, "act", { action: "click", selector: "#dl" });
      const first = await viewer.message("download");
      assert.equal(first.fileName, "report.txt");
      const saved = await NodeFSP.readFile(
        NodePath.join(service.sessionsRoot, chat, "downloads", "report.txt"),
        "utf8",
      );
      assert.equal(saved, "downloaded content");
      await ok(service.socketPath, chat, "act", { action: "click", selector: "#dl" });
      await viewer.message("download", (m) => m.fileName === "report (1).txt");
    } finally {
      viewer.close();
    }
  });

  test("a page cannot save more than the chat's download budget", async () => {
    const chat = newChat();
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    viewer.autoAck = true;
    try {
      await ok(service.socketPath, chat, "open", { url: `${site.url}/download-storm` });
      await viewer.waitFor(() => viewer.messages.filter((m) => m.type === "download").length >= 20);
      // Give the rest of the storm (4 s) time to arrive.
      await new Promise((resolve) => setTimeout(resolve, 4_000));
      assert.equal(viewer.messages.filter((m) => m.type === "download").length, 20);
      const saved = await NodeFSP.readdir(NodePath.join(service.sessionsRoot, chat, "downloads"));
      assert.equal(saved.length, 20);
    } finally {
      viewer.close();
    }
  });

  test("the download budget counts the downloads that the chat already saved", async () => {
    const chat = newChat();
    const dir = NodePath.join(service.sessionsRoot, chat, "downloads");
    await NodeFSP.mkdir(dir, { recursive: true });
    for (let n = 0; n < 20; n += 1) await NodeFSP.writeFile(NodePath.join(dir, `saved-${n}.txt`), "x");
    await ok(service.socketPath, chat, "open", { url: `${site.url}/download-page` });
    await ok(service.socketPath, chat, "act", { action: "click", selector: "#dl" });
    await waitUntil(() => service.events.some((e) => e.event === "download_refused" && e.chat === chat));
    assert.equal((await NodeFSP.readdir(dir)).length, 20);
  });

  test("a popup joins its opener's chat", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/popup` });
    await ok(service.socketPath, chat, "act", { action: "click", selector: "#pop" });
    const deadline = Date.now() + 5_000;
    let tabs: Array<TabJson> = [];
    while (Date.now() < deadline) {
      tabs = (await ok(service.socketPath, chat, "status")).tabs as Array<TabJson>;
      if (tabs.length === 2) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.equal(tabs.length, 2);
    assert.ok(tabs[1]?.url.endsWith("/second"));
    const otherChat = await ok(service.socketPath, newChat(), "status");
    assert.deepEqual(otherChat.tabs, []);
  });

  test("keys that open a dialog return at once and leave the dialog pending", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/key-alert` });
    for (const params of [
      { action: "press", key: "a" },
      { action: "type", text: "abc" },
    ]) {
      const started = Date.now();
      await ok(service.socketPath, chat, "act", { ...params, timeoutMs: 5_000 });
      assert.ok(Date.now() - started < 3_000, `${params.action} waited for the dialog`);
      const status = await ok(service.socketPath, chat, "status");
      assert.deepEqual((status.tabs as Array<{ dialog: unknown }>)[0]?.dialog, {
        type: "alert",
        message: "key",
        origin: site.url,
      });
      await ok(service.socketPath, chat, "dialog", { accept: true });
    }
  });

  test("dialogs block agent writes until answered", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/form` });
    await ok(service.socketPath, chat, "act", {
      action: "click",
      selector: "#btn",
    });
    void call(service.socketPath, chat, "evaluate", { expression: "setTimeout(() => alert('hi'), 0); 1" });
    const deadline = Date.now() + 5_000;
    let dialog: unknown = null;
    while (Date.now() < deadline && dialog === null) {
      const status = await ok(service.socketPath, chat, "status");
      dialog = (status.tabs as Array<{ dialog: unknown }>)[0]?.dialog ?? null;
      if (dialog === null) await new Promise((resolve) => setTimeout(resolve, 50));
    }
    assert.deepEqual(dialog, { type: "alert", message: "hi", origin: site.url });
    const blocked = await call(service.socketPath, chat, "act", { action: "click", selector: "#btn" });
    assert.equal(blocked.ok, false);
    if (!blocked.ok) assert.equal(blocked.error.code, "dialog_pending");
    await ok(service.socketPath, chat, "dialog", { accept: true });
    await ok(service.socketPath, chat, "act", { action: "click", selector: "#btn" });
  });

  test("a viewer that leaves while its new tab opens holds no control", async () => {
    const chat = newChat();
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    try {
      await viewer.message("tabs");
      viewer.send({ type: "newTab" });
      await new Promise((resolve) => setTimeout(resolve, 5));
    } finally {
      viewer.close();
    }
    let tabs: Array<TabJson> = [];
    const deadline = Date.now() + 5_000;
    while (Date.now() < deadline && tabs.length === 0) {
      tabs = (await ok(service.socketPath, chat, "status")).tabs as Array<TabJson>;
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
    assert.equal(tabs.length, 1);
    assert.equal(tabs[0]?.controller, "none");
    await ok(service.socketPath, chat, "evaluate", { tab: tabs[0]?.id, expression: "1" });
  });

  test("a dialog that a viewer navigation dismisses stops blocking the agent", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/alert` });
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    viewer.autoAck = true;
    try {
      await viewer.message("tabs", (m) => (m.tabs as Array<{ dialog: unknown }>)[0]?.dialog !== null);
      viewer.send({ type: "takeControl" });
      await viewer.message("control", (m) => m.controller === "you");
      viewer.send({ type: "navigate", url: `${site.url}/second` });
      await viewer.message("tabs", (m) => {
        const tab = (m.tabs as Array<TabJson & { dialog: unknown }>)[0];
        return tab?.title === "Second page" && tab.dialog === null;
      });
      viewer.send({ type: "releaseControl" });
      await viewer.message("control", (m) => m.controller === "agent");
      await ok(service.socketPath, chat, "evaluate", { expression: "1" });
    } finally {
      viewer.close();
    }
  });

  test("a crashed tab closes so the agent can open another", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/second?crash` });
    // A raw CDP socket: a second Playwright client resets download behavior when it leaves.
    const targets = (await (await fetch(`${chrome.cdpUrl}/json/list`)).json()) as Array<{
      url: string;
      webSocketDebuggerUrl: string;
    }>;
    const target = targets.find((each) => each.url.endsWith("?crash"))!;
    const socket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve) => socket.addEventListener("open", resolve));
    socket.send(JSON.stringify({ id: 1, method: "Page.crash" }));
    try {
      const deadline = Date.now() + 5_000;
      let status = await ok(service.socketPath, chat, "status");
      while (Date.now() < deadline && (status.tabs as Array<TabJson>).length > 0) {
        await new Promise((resolve) => setTimeout(resolve, 100));
        status = await ok(service.socketPath, chat, "status");
      }
      assert.deepEqual(status, { tabs: [], current: null });
      await ok(service.socketPath, chat, "open", { url: `${site.url}/second` });
    } finally {
      socket.close();
    }
  });

  test("a download with a long unicode name is saved", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/second` });
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    viewer.autoAck = true;
    try {
      await viewer.message("viewport");
      const reply = await call(service.socketPath, chat, "navigate", { url: `${site.url}/long-name` });
      assert.equal(reply.ok, false);
      // The budget can refuse the save, so the reply does not promise one.
      if (!reply.ok) assert.match(reply.error.message, /started a download instead of a page; a saved download appears in the chat.s downloads\/ folder/);
      const saved = await viewer.message("download");
      const name = saved.fileName as string;
      assert.ok(name.endsWith(".txt"), name);
      assert.ok(Buffer.byteLength(name) <= 255, name);
      const content = await NodeFSP.readFile(NodePath.join(service.sessionsRoot, chat, "downloads", name), "utf8");
      assert.equal(content, "long");
    } finally {
      viewer.close();
    }
  });

  test("a page with a huge title cannot cut the browser connection", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/second` });
    // Over Playwright's CDP message limit, if the title came back whole.
    await ok(service.socketPath, chat, "evaluate", { expression: "document.title = 'x'.repeat(3e8); 1" });
    // A status read gives up after 250 ms, and this page is slow to answer.
    const deadline = Date.now() + 10_000;
    let title = "";
    while (title.length !== 512 && Date.now() < deadline) {
      title = ((await ok(service.socketPath, chat, "status")).tabs as Array<TabJson>)[0]?.title ?? "";
    }
    assert.equal(title.length, 512);
    const snap = await ok(service.socketPath, chat, "snapshot");
    assert.match(snap.text as string, /^Title: x{512}\n/);
    await ok(service.socketPath, chat, "open", { url: `${site.url}/second`, newTab: true });
  });

  test("a viewer navigation that fails sends the viewer an error", async () => {
    const chat = newChat();
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    viewer.autoAck = true;
    try {
      viewer.send({ type: "newTab", url: `${site.url}/second` });
      await viewer.message("control", (m) => m.controller === "you");
      await viewer.message("tabs", (m) => (m.tabs as Array<TabJson>)[0]?.title === "Second page");
      viewer.send({ type: "navigate", url: "http://127.0.0.1:1/" });
      const error = await viewer.message("error");
      assert.match(error.message as string, /^Navigation to http:\/\/127\.0\.0\.1:1\/ failed: ERR_/);
    } finally {
      viewer.close();
    }
  });

  test("an agent upload by selector closes the pending file chooser", async () => {
    const chat = newChat();
    const dir = NodePath.join(service.sessionsRoot, chat);
    await NodeFSP.mkdir(dir, { recursive: true });
    await NodeFSP.writeFile(NodePath.join(dir, "a.csv"), "a");
    await NodeFSP.writeFile(NodePath.join(dir, "b.csv"), "b");
    await ok(service.socketPath, chat, "open", { url: `${site.url}/upload` });
    const center = await boxOf(service.socketPath, chat, "#file");
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    viewer.autoAck = true;
    try {
      viewer.send({ type: "takeControl" });
      await viewer.message("control", (m) => m.controller === "you");
      clickAt(viewer, center.x, center.y);
      const chooser = await viewer.message("fileChooser");
      viewer.send({ type: "releaseControl" });
      await viewer.message("control", (m) => m.controller === "agent");
      await ok(service.socketPath, chat, "act", { action: "upload", selector: "#file", paths: ["a.csv"] });
      await viewer.message("fileChooserClosed", (m) => m.id === chooser.id);
      const untargeted = await call(service.socketPath, chat, "act", { action: "upload", paths: ["b.csv"] });
      assert.equal(untargeted.ok, false);
      await ok(service.socketPath, chat, "waitFor", { text: "picked a.csv" });
    } finally {
      viewer.close();
    }
  });

  test("a path through a symlink cannot leave the chat session dir", async () => {
    const chat = newChat();
    const dir = NodePath.join(service.sessionsRoot, chat);
    const outside = await NodeFSP.mkdtemp(NodePath.join(NodeOS.tmpdir(), "onyx-browser-outside-"));
    try {
      await NodeFSP.writeFile(NodePath.join(outside, "secret.txt"), "secret");
      await NodeFSP.mkdir(dir, { recursive: true });
      await NodeFSP.symlink(NodePath.join(outside, "secret.txt"), NodePath.join(dir, "link.txt"));
      await NodeFSP.symlink(outside, NodePath.join(dir, "out"));
      await NodeFSP.symlink(NodePath.join(outside, "new.png"), NodePath.join(dir, "dangling.png"));
      await ok(service.socketPath, chat, "open", { url: `${site.url}/upload` });
      for (const path of ["link.txt", "out/secret.txt"]) {
        const reply = await call(service.socketPath, chat, "act", { action: "upload", selector: "#file", paths: [path] });
        assert.equal(reply.ok ? "ok" : reply.error.code, "invalid_argument", path);
      }
      for (const path of ["out/shot.png", "out/sub/shot.png", "dangling.png"]) {
        const reply = await call(service.socketPath, chat, "snapshot", { screenshotPath: path });
        assert.equal(reply.ok ? "ok" : reply.error.code, "invalid_argument", path);
      }
      assert.deepEqual(await NodeFSP.readdir(outside), ["secret.txt"]);
    } finally {
      await NodeFSP.rm(outside, { recursive: true, force: true });
    }
  });

  test("a download that passes the budget stops while it downloads", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/second` });
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    viewer.autoAck = true;
    try {
      await viewer.message("viewport");
      const stopped = site.bigDownloadsStopped;
      await call(service.socketPath, chat, "navigate", { url: `${site.url}/big-download` });
      await viewer.waitFor(() => site.bigDownloadsStopped > stopped, 30_000);
      const saved = await NodeFSP.readdir(NodePath.join(service.sessionsRoot, chat, "downloads")).catch(() => []);
      assert.deepEqual(saved, []);
      assert.ok(!viewer.messages.some((m) => m.type === "download"));
    } finally {
      viewer.close();
    }
  });

  test("downloads that run at the same time share the budget", async () => {
    const chat = newChat();
    const stopped = site.bigDownloadsStopped;
    await Promise.all(
      [1, 2].map((n) =>
        call(service.socketPath, chat, "open", {
          url: `${site.url}/big-download?chunkMiB=4&chunks=50&n=${n}`,
          newTab: true,
        }),
      ),
    );
    await waitUntil(() => site.bigDownloadsStopped > stopped, 30_000);
    assert.ok(site.bigDownloadsPeak >= 2, "the downloads did not overlap");
    const dir = NodePath.join(service.sessionsRoot, chat, "downloads");
    const size = async (name: string) => (await NodeFSP.stat(NodePath.join(dir, name))).size;
    const saved = async () => await NodeFSP.readdir(dir).catch((): Array<string> => []);
    await waitUntil(async () => {
      const names = await saved();
      return names.length === 1 && (await size(names[0]!)) === 200 * 1024 * 1024;
    }, 30_000);
    assert.equal((await saved()).length, 1);
  });

  test("a download that starts in a popup counts against the chat budget", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/popup-download` });
    const stopped = site.bigDownloadsStopped;
    await ok(service.socketPath, chat, "act", { action: "click", selector: "#pop" });
    await waitUntil(() => site.bigDownloadsStopped > stopped, 30_000);
    const saved = await NodeFSP.readdir(NodePath.join(service.sessionsRoot, chat, "downloads")).catch(() => []);
    assert.deepEqual(saved, []);
  });

  test("select by label picks that option when two options share a value", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/second` });
    await ok(service.socketPath, chat, "evaluate", {
      expression: `document.body.innerHTML = '<select id="s"><option value="delivery">Standard</option><option value="delivery">Express</option></select>'; 1`,
    });
    await ok(service.socketPath, chat, "act", { action: "select", selector: "#s", values: ["Express"] });
    const index = await ok(service.socketPath, chat, "evaluate", { expression: "document.getElementById('s').selectedIndex" });
    assert.equal(index.value, 1);
  });

  test("a reply over the frame limit becomes an error the agent can read", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/second` });
    await ok(service.socketPath, chat, "evaluate", {
      expression: `document.body.innerHTML = '<select id="s"><option>None</option><option>Big</option></select>'; document.querySelectorAll('option')[1].value = 'x'.repeat(${MAX_FRAME_LENGTH}); 1`,
    });
    const reply = await call(service.socketPath, chat, "act", { action: "select", selector: "#s", values: ["Big"] });
    assert.equal(reply.ok, false);
    if (!reply.ok) assert.equal(reply.error.code, "failed");
  });

  test("type with clear types into the field when the page moves focus on clear", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/second` });
    await ok(service.socketPath, chat, "evaluate", {
      expression: `document.body.innerHTML = '<input id="a" value="old"><input id="b">'; document.getElementById('a').addEventListener('input', (e) => { if (e.target.value === '') document.getElementById('b').focus(); }); 1`,
    });
    await ok(service.socketPath, chat, "act", { action: "type", selector: "#a", text: "new", clear: true });
    const values = await ok(service.socketPath, chat, "evaluate", {
      expression: "[document.getElementById('a').value, document.getElementById('b').value]",
    });
    assert.deepEqual(values.value, ["new", ""]);
  });

  test("time spent queued counts against an evaluation's timeout", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/second` });
    const busy = ok(service.socketPath, chat, "evaluate", {
      expression: "new Promise((resolve) => setTimeout(() => resolve(1), 1500))",
    });
    await new Promise((resolve) => setTimeout(resolve, 200));
    const queued = await call(service.socketPath, chat, "evaluate", {
      expression: "new Promise((resolve) => setTimeout(() => resolve(2), 1000))",
      timeoutMs: 2_000,
    });
    assert.equal((await busy).value, 1);
    assert.equal(queued.ok, false);
    if (!queued.ok) assert.equal(queued.error.code, "timeout");
  });

  test("a queued read runs after a viewer takes and releases control", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/form` });
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    viewer.autoAck = true;
    try {
      await viewer.message("control", (m) => m.controller === "agent");
      const busy = ok(service.socketPath, chat, "evaluate", {
        expression: "new Promise((resolve) => setTimeout(() => resolve(1), 1500))",
      });
      await new Promise((resolve) => setTimeout(resolve, 200));
      const read = call(service.socketPath, chat, "snapshot");
      await new Promise((resolve) => setTimeout(resolve, 200));
      viewer.send({ type: "takeControl" });
      await viewer.message("control", (m) => m.controller === "you");
      viewer.messages.length = 0;
      viewer.send({ type: "releaseControl" });
      await viewer.message("control", (m) => m.controller !== "you");
      assert.equal((await busy).value, 1);
      const snap = await read;
      assert.ok(snap.ok, JSON.stringify(snap));
    } finally {
      viewer.close();
    }
  });

  test("a download that does not save gives its slot back", async () => {
    const chat = newChat();
    const dir = NodePath.join(service.sessionsRoot, chat, "downloads");
    await NodeFSP.mkdir(dir, { recursive: true });
    for (let n = 0; n < 19; n += 1) await NodeFSP.writeFile(NodePath.join(dir, `saved-${n}.txt`), "x");
    await ok(service.socketPath, chat, "open", { url: `${site.url}/download-page` });
    const stopped = site.bigDownloadsStopped;
    await ok(service.socketPath, chat, "evaluate", { expression: "document.getElementById('dl').href = '/big-download'; 1" });
    await ok(service.socketPath, chat, "act", { action: "click", selector: "#dl" });
    await waitUntil(() => site.bigDownloadsStopped > stopped, 30_000);
    await ok(service.socketPath, chat, "evaluate", { expression: "document.getElementById('dl').href = '/file.txt'; 1" });
    await ok(service.socketPath, chat, "act", { action: "click", selector: "#dl" });
    await waitUntil(async () => (await NodeFSP.readdir(dir)).includes("report.txt"));
  });

  test("a downloads folder that links outside the chat gets no file", async () => {
    const chat = newChat();
    const outside = await NodeFSP.mkdtemp(NodePath.join(NodeOS.tmpdir(), "onyx-browser-outside-"));
    try {
      await NodeFSP.mkdir(NodePath.join(service.sessionsRoot, chat), { recursive: true });
      await NodeFSP.symlink(outside, NodePath.join(service.sessionsRoot, chat, "downloads"));
      await ok(service.socketPath, chat, "open", { url: `${site.url}/download-page` });
      await ok(service.socketPath, chat, "act", { action: "click", selector: "#dl" });
      await waitUntil(() => service.events.some((e) => e.event === "download_failed" && e.chat === chat));
      assert.deepEqual(await NodeFSP.readdir(outside), []);
    } finally {
      await NodeFSP.rm(outside, { recursive: true, force: true });
    }
  });

  test("dialogs and file choosers report the origin of the frame that opened them", async () => {
    const chat = newChat();
    await ok(service.socketPath, chat, "open", { url: `${site.url}/cross-frame?inner=frame-alert` });
    const viewer = await ViewerClient.connect(service.socketPath, chat);
    viewer.autoAck = true;
    try {
      await viewer.message("tabs", (m) => {
        const dialog = (m.tabs as Array<{ dialog: { origin: unknown } | null }>)[0]?.dialog;
        return dialog?.origin === site.crossUrl;
      });
      const status = await ok(service.socketPath, chat, "status");
      assert.deepEqual((status.tabs as Array<{ dialog: unknown }>)[0]?.dialog, {
        type: "alert",
        message: "from frame",
        origin: site.crossUrl,
      });
      await ok(service.socketPath, chat, "dialog", { accept: true });

      await ok(service.socketPath, chat, "navigate", { url: `${site.url}/cross-frame?inner=frame-upload` });
      await ok(service.socketPath, chat, "act", {
        action: "click",
        selector: "iframe >> internal:control=enter-frame >> #file",
      });
      viewer.send({ type: "takeControl" });
      const chooser = await viewer.message("fileChooser");
      assert.equal(chooser.origin, site.crossUrl);
    } finally {
      viewer.close();
    }
  });

  test("bad requests get invalid_argument", async () => {
    const chat = newChat();
    const bad = await call(service.socketPath, chat, "open", { url: "javascript:alert(1)" });
    assert.equal(bad.ok, false);
    if (!bad.ok) assert.equal(bad.error.code, "invalid_argument");
    const unknown = await call(service.socketPath, chat, "fly");
    assert.equal(unknown.ok, false);
    const badChat = await call(service.socketPath, "NOT-A-UUID", "status");
    assert.equal(badChat.ok, false);
    if (!badChat.ok) assert.equal(badChat.error.code, "invalid_argument");
  });
});
