import { describe, expect, it } from "@jest/globals";

import { getErrorTitle } from "@/chat/errorHelpers";

describe("getErrorTitle", () => {
  it("maps known error codes to friendly titles", () => {
    expect(getErrorTitle("RATE_LIMIT")).toBe("Rate Limit Exceeded");
    expect(getErrorTitle("AUTH_ERROR")).toBe("Authentication Error");
    expect(getErrorTitle("SERVICE_UNAVAILABLE")).toBe("Service Unavailable");
  });

  it("falls back to 'Error' for unknown, null, or missing codes", () => {
    expect(getErrorTitle(undefined)).toBe("Error");
    expect(getErrorTitle(null)).toBe("Error");
    expect(getErrorTitle("SOMETHING_UNMAPPED")).toBe("Error");
  });
});
