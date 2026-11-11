import { fetchDirectoryListing } from "@/app/craft/services/apiServices";
import {
  loadSearchInventory,
  MAX_SEARCH_ENTRIES,
} from "@/app/craft/services/workspaceFiles";

jest.mock("@/app/craft/services/apiServices", () => ({
  fetchDirectoryListing: jest.fn(),
}));
const listing = jest.mocked(fetchDirectoryListing);
afterEach(() => jest.restoreAllMocks());
beforeEach(() => jest.clearAllMocks());

test("stops a deep workspace at the directory budget and reports a partial result", async () => {
  listing.mockImplementation(async (_session, path = "") => ({
    path,
    entries: [
      {
        name: "child",
        path: `${path ? `${path}/` : ""}child`,
        is_directory: true,
        size: null,
        mime_type: null,
      },
    ],
  }));
  const result = await loadSearchInventory(
    "session",
    new AbortController().signal
  );
  expect(listing).toHaveBeenCalledTimes(128);
  expect(result.complete).toBe(false);
  expect(result.failedDirectories).toHaveLength(1);
});

test("caps file entries and marks the partially read directory", async () => {
  listing.mockResolvedValue({
    path: "",
    entries: Array.from({ length: MAX_SEARCH_ENTRIES + 1 }, (_, i) => ({
      name: `file-${i}`,
      path: `file-${i}`,
      is_directory: false,
      size: 1,
      mime_type: "text/plain",
    })),
  });
  const result = await loadSearchInventory(
    "session",
    new AbortController().signal
  );
  expect(result.entries).toHaveLength(MAX_SEARCH_ENTRIES);
  expect(result.complete).toBe(false);
  expect(result.failedDirectories).toEqual([""]);
});

test("returns accepted files when a completed batch exhausts the time budget", async () => {
  let now = 0;
  jest.spyOn(Date, "now").mockImplementation(() => now);
  listing.mockImplementation(async () => {
    now = 10_001;
    return {
      path: "",
      entries: [
        {
          name: "next",
          path: "next",
          is_directory: true,
          size: null,
          mime_type: null,
        },
        {
          name: "file",
          path: "file",
          is_directory: false,
          size: 1,
          mime_type: "text/plain",
        },
      ],
    };
  });
  const result = await loadSearchInventory(
    "session",
    new AbortController().signal
  );
  expect(listing).toHaveBeenCalledTimes(1);
  expect(result.entries.map((entry) => entry.path)).toEqual(["file"]);
  expect(result.failedDirectories).toEqual(["next"]);
  expect(result.complete).toBe(false);
});
