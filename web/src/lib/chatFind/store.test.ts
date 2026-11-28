import {
  closeChatFind,
  mountChatFind,
  openChatFind,
  useChatFindStore,
} from "@/lib/chatFind/store";

afterEach(closeChatFind);

test("find opens only while a chat's find bar is mounted", () => {
  openChatFind();
  expect(useChatFindStore.getState().open).toBe(false);

  const unmount = mountChatFind();
  openChatFind();
  expect(useChatFindStore.getState().open).toBe(true);

  unmount();
  closeChatFind();
  openChatFind();
  expect(useChatFindStore.getState().open).toBe(false);
});
