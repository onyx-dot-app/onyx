import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { loadOlderChatMessages } from "@/lib/chat/pagedSession";
import { loadOlderPagesForFind } from "@/lib/chatFind/olderPages";

jest.mock("@/lib/chat/pagedSession", () => ({
  loadOlderChatMessages: jest.fn(),
}));

const SESSION = "chat-1";
const mockLoad = jest.mocked(loadOlderChatMessages);

/** A chat with `pages` older pages left; each load takes one. */
function chatWithOlderPages(pages: number) {
  let left = pages;
  useChatSessionStore.getState().updateSessionData(SESSION, {
    hasOlderMessages: left > 0,
    isLoadingOlderMessages: false,
  });
  mockLoad.mockImplementation(async () => {
    left -= 1;
    useChatSessionStore
      .getState()
      .updateSessionData(SESSION, { hasOlderMessages: left > 0 });
  });
}

beforeEach(() => mockLoad.mockReset());

test("loads every older page, one at a time, until none are left", async () => {
  chatWithOlderPages(3);
  await expect(loadOlderPagesForFind(SESSION, () => false)).resolves.toBe(
    false
  );
  expect(mockLoad).toHaveBeenCalledTimes(3);
  expect(mockLoad).toHaveBeenCalledWith(SESSION);
});

test("stops at the page cap and reports older messages left", async () => {
  chatWithOlderPages(5);
  await expect(loadOlderPagesForFind(SESSION, () => false, 2)).resolves.toBe(
    true
  );
  expect(mockLoad).toHaveBeenCalledTimes(2);
});

test("stops when cancelled", async () => {
  chatWithOlderPages(5);
  let cancelled = false;
  mockLoad.mockImplementation(async () => {
    cancelled = true;
  });
  await loadOlderPagesForFind(SESSION, () => cancelled);
  expect(mockLoad).toHaveBeenCalledTimes(1);
});
