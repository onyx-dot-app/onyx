/** @jest-environment jsdom */
import {
  mintMcpChatEnableIntent,
  verifyMcpChatEnableIntent,
  clearMcpChatEnableIntent,
} from "@/sections/actions/mcpChatEnableIntent";

const scope = { userId: "admin-user", serverId: 7 };
beforeEach(() => sessionStorage.clear());
afterEach(() => jest.restoreAllMocks());

test("an explicit intent stays valid until it is cleared", () => {
  const token = mintMcpChatEnableIntent(scope);
  expect(token).toEqual(expect.any(String));
  expect(verifyMcpChatEnableIntent(token, scope)).toBe(true);
  expect(verifyMcpChatEnableIntent(token, scope)).toBe(true);
  clearMcpChatEnableIntent(token);
  expect(verifyMcpChatEnableIntent(token, scope)).toBe(false);
});

test("mints a valid intent on insecure origins without randomUUID", () => {
  const original = crypto.randomUUID;
  Object.defineProperty(crypto, "randomUUID", {
    value: undefined,
    configurable: true,
  });
  try {
    const token = mintMcpChatEnableIntent(scope);
    expect(token).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
    );
    expect(verifyMcpChatEnableIntent(token, scope)).toBe(true);
  } finally {
    Object.defineProperty(crypto, "randomUUID", {
      value: original,
      configurable: true,
    });
  }
});

test.each([
  { userId: "another-user", serverId: 7 },
  { userId: "admin-user", serverId: 8 },
])("rejects a mismatched actor or server: %j", (other) => {
  const token = mintMcpChatEnableIntent(scope);
  expect(verifyMcpChatEnableIntent(token, other)).toBe(false);
  expect(verifyMcpChatEnableIntent(token, scope)).toBe(true);
});

test("expires after one five-minute OAuth round trip", () => {
  jest.spyOn(Date, "now").mockReturnValue(1_000_000);
  const token = mintMcpChatEnableIntent(scope);
  jest.mocked(Date.now).mockReturnValue(1_300_000);
  expect(verifyMcpChatEnableIntent(token, scope)).toBe(false);
});

test("cancellation clears only the matching active intent", () => {
  const old = mintMcpChatEnableIntent(scope);
  const token = mintMcpChatEnableIntent(scope);
  clearMcpChatEnableIntent(old);
  expect(verifyMcpChatEnableIntent(old, scope)).toBe(false);
  clearMcpChatEnableIntent(token);
  expect(verifyMcpChatEnableIntent(token, scope)).toBe(false);
});

test("a return without this tab's stored proof fails closed", () => {
  const token = mintMcpChatEnableIntent(scope);
  sessionStorage.clear();
  expect(verifyMcpChatEnableIntent(token, scope)).toBe(false);
});

test("blocked storage cannot mint or verify proof", () => {
  jest.spyOn(window, "sessionStorage", "get").mockImplementation(() => {
    throw new Error("Blocked");
  });
  expect(mintMcpChatEnableIntent(scope)).toBeNull();
  expect(verifyMcpChatEnableIntent("forged", scope)).toBe(false);
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
  expect(verifyMcpChatEnableIntent(token, scope)).toBe(false);
});

test("malformed stored data fails closed", () => {
  sessionStorage.setItem("onyx:mcp-chat-enable", "not-json");
  expect(verifyMcpChatEnableIntent("forged", scope)).toBe(false);
});
