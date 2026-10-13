/** @jest-environment jsdom */

import { mutate } from "swr";
import { logout } from "@/lib/users/svc";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  readOutputPanelPreferences,
  saveOutputPanelPreferences,
} from "@/app/craft/services/outputPanelPreferences";

import {
  createOutputThumbnailCache,
  readOutputThumbnailCache,
  retainOutputThumbnailCache,
} from "@/app/craft/services/outputThumbnailCache";

jest.mock("swr", () => ({ mutate: jest.fn() }));

beforeEach(() => {
  sessionStorage.clear();
  for (const sessionId of ["first-session", "second-session"]) {
    saveOutputPanelPreferences(sessionId, {
      outputPanelMode: "medium",
      outputPanelInitialized: true,
      panelTabs: [
        { kind: "file", path: "outputs/private.txt", fileName: "private.txt" },
      ],
      activePanelTabId: "file:outputs/private.txt",
      mediumPanelProportion: 0.5,
    });
  }
  sessionStorage.setItem("unrelated-preference", "keep");
  sessionStorage.setItem(
    "onyx:craft:directories:v1:user:session",
    "private names"
  );
  sessionStorage.setItem(
    "onyx:craft:outputs:v1:user:session",
    "private outputs"
  );
  sessionStorage.setItem(
    "onyx:craft:output-thumbnails:v1:user",
    "private bytes"
  );
  retainOutputThumbnailCache(
    "user",
    createOutputThumbnailCache(128, 16 * 1024 * 1024, "user")
  );
});

afterEach(() => jest.restoreAllMocks());

test("successful logout removes all saved Craft tab names and preserves unrelated preferences", async () => {
  const response = new Response(null, { status: 204 });
  jest.spyOn(global, "fetch").mockResolvedValue(response);

  expect(await logout()).toBe(response);

  expect(readOutputPanelPreferences("first-session")).toBeUndefined();
  expect(readOutputPanelPreferences("second-session")).toBeUndefined();
  expect(sessionStorage.getItem("unrelated-preference")).toBe("keep");
  expect(sessionStorage.length).toBe(1);
  expect(readOutputThumbnailCache("user")).toBeUndefined();
  expect(mutate).toHaveBeenCalledWith(SWR_KEYS.me, null, { revalidate: false });
});

test("failed logout retains the signed-in user's saved tabs", async () => {
  const response = new Response(null, { status: 500 });
  jest.spyOn(global, "fetch").mockResolvedValue(response);

  expect(await logout()).toBe(response);

  expect(readOutputPanelPreferences("first-session")?.panelTabs).toHaveLength(
    1
  );
  expect(readOutputPanelPreferences("second-session")?.panelTabs).toHaveLength(
    1
  );
  expect(mutate).not.toHaveBeenCalled();
});

test("unavailable browser storage does not prevent successful logout", async () => {
  const response = new Response(null, { status: 204 });
  jest.spyOn(global, "fetch").mockResolvedValue(response);
  jest.spyOn(window, "sessionStorage", "get").mockImplementation(() => {
    throw new DOMException("Storage unavailable", "SecurityError");
  });

  expect(await logout()).toBe(response);
  expect(mutate).toHaveBeenCalledWith(SWR_KEYS.me, null, { revalidate: false });
});
