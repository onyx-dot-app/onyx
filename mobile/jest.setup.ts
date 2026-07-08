import { beforeEach, jest } from "@jest/globals";

// requireMock reaches the manual mock's test-only reset helper, bypassing the real module's types.
const secureStoreMock = jest.requireMock("expo-secure-store") as {
  __resetSecureStore: () => void;
};

beforeEach(() => {
  secureStoreMock.__resetSecureStore();
  jest.clearAllMocks();
});
