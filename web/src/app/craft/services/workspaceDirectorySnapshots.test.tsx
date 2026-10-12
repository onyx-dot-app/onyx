import {
  clearWorkspaceDirectorySnapshots,
  readWorkspaceDirectorySnapshot,
  saveWorkspaceDirectorySnapshot,
} from "@/app/craft/services/workspaceDirectorySnapshots";
import type { DirectoryListing } from "@/app/craft/types/streamingTypes";

const listing: DirectoryListing = {
  path: "outputs",
  entries: [
    {
      name: "report.csv",
      path: "outputs/report.csv",
      is_directory: false,
      size: 50,
      mime_type: "text/csv",
    },
  ],
};

beforeEach(() => window.sessionStorage.clear());
afterEach(() => jest.restoreAllMocks());

it("scopes directory metadata by user, session and path", () => {
  saveWorkspaceDirectorySnapshot("user-a", "session-a", listing);
  expect(
    readWorkspaceDirectorySnapshot("user-a", "session-a", "outputs")
  ).toEqual(listing);
  expect(
    readWorkspaceDirectorySnapshot("user-b", "session-a", "outputs")
  ).toBeUndefined();
  expect(
    readWorkspaceDirectorySnapshot("user-a", "session-b", "outputs")
  ).toBeUndefined();
  expect(
    readWorkspaceDirectorySnapshot("user-a", "session-a", "other")
  ).toBeUndefined();
  clearWorkspaceDirectorySnapshots("user-a", "session-a");
  expect(
    readWorkspaceDirectorySnapshot("user-a", "session-a", "outputs")
  ).toBeUndefined();
});

it("ignores expired and malformed snapshots", () => {
  saveWorkspaceDirectorySnapshot("user", "session", listing);
  const now = Date.now();
  jest.spyOn(Date, "now").mockReturnValue(now + 24 * 60 * 60 * 1000 + 1);
  expect(
    readWorkspaceDirectorySnapshot("user", "session", "outputs")
  ).toBeUndefined();
  window.sessionStorage.setItem(
    "onyx:craft:directories:v1:user:session",
    JSON.stringify([
      { readAt: now, listing: { path: "outputs", entries: [{ name: "bad" }] } },
    ])
  );
  expect(
    readWorkspaceDirectorySnapshot("user", "session", "outputs")
  ).toBeUndefined();
});

it("bounds stored directory count and serialized size", () => {
  for (let index = 0; index < 40; index++)
    saveWorkspaceDirectorySnapshot("user", "session", {
      path: `folder-${index}`,
      entries: [],
    });
  expect(
    readWorkspaceDirectorySnapshot("user", "session", "folder-0")
  ).toBeUndefined();
  expect(
    readWorkspaceDirectorySnapshot("user", "session", "folder-39")
  ).toBeDefined();
  saveWorkspaceDirectorySnapshot("user", "session", {
    path: "huge",
    entries: [
      {
        name: "x".repeat(300_000),
        path: "huge/file",
        is_directory: false,
        size: 10,
        mime_type: "text/plain",
      },
    ],
  });
  expect(
    readWorkspaceDirectorySnapshot("user", "session", "huge")
  ).toBeUndefined();
  expect(
    window.sessionStorage.getItem("onyx:craft:directories:v1:user:session")
      ?.length
  ).toBeLessThanOrEqual(256_000);
});

it("allows reads to continue when browser storage is blocked", () => {
  jest.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  jest.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  jest.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  expect(
    readWorkspaceDirectorySnapshot("user", "session", "outputs")
  ).toBeUndefined();
  expect(() =>
    saveWorkspaceDirectorySnapshot("user", "session", listing)
  ).not.toThrow();
  expect(() =>
    clearWorkspaceDirectorySnapshots("user", "session")
  ).not.toThrow();
});
