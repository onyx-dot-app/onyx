/** @jest-environment jsdom */
import {
  readOutputInventorySnapshot,
  saveOutputInventorySnapshot,
  clearOutputInventorySnapshot,
} from "@/app/craft/services/outputInventorySnapshots";

const file = { path: "outputs/report.csv", revision: "1:50", size: 50 };
const files = { [file.path]: file };
const key = "onyx:craft:outputs:v1:user:session";

beforeEach(() => sessionStorage.clear());
afterEach(() => jest.restoreAllMocks());

it("restores metadata after reload, scoped to its user and session", () => {
  saveOutputInventorySnapshot("user", "session", files);
  expect(readOutputInventorySnapshot("user", "session")).toEqual(files);
  expect(readOutputInventorySnapshot("other", "session")).toBeUndefined();
  expect(readOutputInventorySnapshot("user", "other")).toBeUndefined();
  clearOutputInventorySnapshot("user", "session");
  expect(readOutputInventorySnapshot("user", "session")).toBeUndefined();
});

it.each([
  "not json",
  JSON.stringify({
    readAt: Date.now(),
    files: [{ ...file, path: "outputs/../secret" }],
  }),
  JSON.stringify({ readAt: Date.now(), files: [file, file] }),
  JSON.stringify({ readAt: Date.now(), files: [{ ...file, size: -1 }] }),
  JSON.stringify({ readAt: Date.now(), files: [{ ...file, revision: null }] }),
  JSON.stringify({ readAt: Date.now() + 60_000, files: [file] }),
])("ignores invalid saved metadata (%s)", (raw) => {
  sessionStorage.setItem(key, raw);
  expect(readOutputInventorySnapshot("user", "session")).toBeUndefined();
});

it("expires snapshots instead of treating old metadata as fresh", () => {
  saveOutputInventorySnapshot("user", "session", files);
  const now = Date.now();
  jest.spyOn(Date, "now").mockReturnValue(now + 24 * 60 * 60 * 1000 + 1);
  expect(readOutputInventorySnapshot("user", "session")).toBeUndefined();
});

it("removes an older snapshot when its replacement exceeds the size bound", () => {
  saveOutputInventorySnapshot("user", "session", files);
  saveOutputInventorySnapshot("user", "session", {
    [file.path]: { ...file, revision: "x".repeat(256_001) },
  });
  expect(readOutputInventorySnapshot("user", "session")).toBeUndefined();
});

it("keeps live reads independent of blocked browser storage", () => {
  jest.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("Blocked");
  });
  jest.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("Blocked");
  });
  expect(() =>
    saveOutputInventorySnapshot("user", "session", files)
  ).not.toThrow();
  expect(readOutputInventorySnapshot("user", "session")).toBeUndefined();
});
