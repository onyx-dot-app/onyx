import { describe, expect, it } from "@jest/globals";

import { QUERY_KEYS } from "@/api/query-keys";

describe("QUERY_KEYS", () => {
  it("scopes the current-user cache by server URL", () => {
    expect(QUERY_KEYS.me("https://one.example")).not.toEqual(
      QUERY_KEYS.me("https://two.example"),
    );
  });
});
