import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import * as SecureStore from "expo-secure-store";

import { getToken, setToken } from "@/api/auth/tokenStore";

let mockBaseUrl = "https://one.example";

jest.mock("@/api/config", () => ({
  getBaseUrl: () => mockBaseUrl,
}));

// expo-secure-store is auto-mocked (__mocks__/expo-secure-store.ts) and reset per test (jest.setup.ts).
const mockSetItemAsync = SecureStore.setItemAsync as unknown as Mock<
  (
    key: string,
    value: string,
    options?: SecureStore.SecureStoreOptions,
  ) => Promise<void>
>;

beforeEach(() => {
  mockBaseUrl = "https://one.example";
});

describe("tokenStore", () => {
  it("does not reuse one instance's token for another instance", async () => {
    await setToken("one-token");

    mockBaseUrl = "https://two.example";

    await expect(getToken()).resolves.toBeNull();
  });

  it("deletes only the current instance's token", async () => {
    await setToken("one-token");

    mockBaseUrl = "https://two.example";
    await setToken("two-token");
    await setToken(null);

    await expect(getToken()).resolves.toBeNull();

    mockBaseUrl = "https://one.example";

    await expect(getToken()).resolves.toBe("one-token");
    expect(mockSetItemAsync.mock.calls[0][0]).not.toBe(
      mockSetItemAsync.mock.calls[1][0],
    );
  });
});
