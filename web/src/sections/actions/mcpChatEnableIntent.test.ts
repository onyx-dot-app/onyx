/** @jest-environment jsdom */
import {
  mintMcpChatEnableIntent,
  consumeMcpChatEnableIntent,
  clearMcpChatEnableIntent,
} from "@/sections/actions/mcpChatEnableIntent";

const scope = { userId: "admin-user", serverId: 7 };
beforeEach(() => sessionStorage.clear());
afterEach(() => jest.restoreAllMocks());

test("an explicit intent authorizes one matching consumption only", () => {
  const token = mintMcpChatEnableIntent(scope);
  expect(token).toEqual(expect.any(String));
  expect(consumeMcpChatEnableIntent(token, scope)).toBe(true);
  expect(consumeMcpChatEnableIntent(token, scope)).toBe(false);
});

test.each([
  { userId: "another-user", serverId: 7 },
  { userId: "admin-user", serverId: 8 },
])("rejects a mismatched actor or server: %j", (other) => {
  const token = mintMcpChatEnableIntent(scope);
  expect(consumeMcpChatEnableIntent(token, other)).toBe(false);
  expect(consumeMcpChatEnableIntent(token, scope)).toBe(false);
});

test("expires after one five-minute OAuth round trip", () => {
  jest.spyOn(Date, "now").mockReturnValue(1_000_000);
  const token = mintMcpChatEnableIntent(scope);
  jest.mocked(Date.now).mockReturnValue(1_300_000);
  expect(consumeMcpChatEnableIntent(token, scope)).toBe(false);
});

test("cancellation clears only the matching active intent", () => {
  const old = mintMcpChatEnableIntent(scope);
  const token = mintMcpChatEnableIntent(scope);
  clearMcpChatEnableIntent(old);
  expect(consumeMcpChatEnableIntent(old, scope)).toBe(false);
  clearMcpChatEnableIntent(token);
  expect(consumeMcpChatEnableIntent(token, scope)).toBe(false);
});

test("a return without this tab's stored proof fails closed", () => {
  const token = mintMcpChatEnableIntent(scope);
  sessionStorage.clear();
  expect(consumeMcpChatEnableIntent(token, scope)).toBe(false);
});

test("blocked storage cannot mint or consume proof", () => {
  jest.spyOn(window, "sessionStorage", "get").mockImplementation(() => {
    throw new Error("Blocked");
  });
  expect(mintMcpChatEnableIntent(scope)).toBeNull();
  expect(consumeMcpChatEnableIntent("forged", scope)).toBe(false);
});

test("signed-out users cannot mint proof", () => {
  expect(
    mintMcpChatEnableIntent({ userId: undefined, serverId: 7 })
  ).toBeNull();
});

test("rejects a stored proof for another origin", () => {
  const token = mintMcpChatEnableIntent(scope);
  sessionStorage.setItem(
    "onyx:mcp-chat-enable",
    JSON.stringify({
      ...scope,
      token,
      origin: "https://another-workspace.example.com",
      expiresAt: Date.now() + 300_000,
    })
  );
  expect(consumeMcpChatEnableIntent(token, scope)).toBe(false);
  expect(sessionStorage.getItem("onyx:mcp-chat-enable")).toBeNull();
});

test("malformed stored data fails closed", () => {
  sessionStorage.setItem("onyx:mcp-chat-enable", "not-json");
  expect(consumeMcpChatEnableIntent("forged", scope)).toBe(false);
});
