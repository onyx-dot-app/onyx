import { ReadonlyURLSearchParams } from "next/navigation";
import {
  SEARCH_PARAM_NAMES,
  getAgentIdFromSearchParam,
  shouldSendOnLoad,
  shouldSubmitOnLoad,
} from "@/app/app/services/searchParams";

function buildSearchParams(query: string): ReadonlyURLSearchParams {
  return new URLSearchParams(query) as unknown as ReadonlyURLSearchParams;
}

describe("shouldSubmitOnLoad", () => {
  it.each(["true", "1"])("returns true for submit-on-load=%s", (flagValue) => {
    const searchParams = buildSearchParams(`submit-on-load=${flagValue}`);
    expect(shouldSubmitOnLoad(searchParams)).toBe(true);
  });

  it.each(["false", "0", "yes", ""])(
    "returns false for submit-on-load=%s",
    (flagValue) => {
      const searchParams = buildSearchParams(`submit-on-load=${flagValue}`);
      expect(shouldSubmitOnLoad(searchParams)).toBe(false);
    }
  );

  it("returns false when the param is absent", () => {
    expect(shouldSubmitOnLoad(buildSearchParams(""))).toBe(false);
  });

  it("returns false for null search params", () => {
    expect(shouldSubmitOnLoad(null)).toBe(false);
  });
});

describe("shouldSendOnLoad", () => {
  it.each(["true", "1"])("returns true for send-on-load=%s", (flagValue) => {
    const searchParams = buildSearchParams(`send-on-load=${flagValue}`);
    expect(shouldSendOnLoad(searchParams)).toBe(true);
  });

  // Regression: a truthiness check on the raw string auto-sent the message
  // even when the param was explicitly "false".
  it.each(["false", "0", "yes", ""])(
    "returns false for send-on-load=%s",
    (flagValue) => {
      const searchParams = buildSearchParams(`send-on-load=${flagValue}`);
      expect(shouldSendOnLoad(searchParams)).toBe(false);
    }
  );

  it("returns false when the param is absent", () => {
    expect(shouldSendOnLoad(buildSearchParams(""))).toBe(false);
  });

  it("returns false for null search params", () => {
    expect(shouldSendOnLoad(null)).toBe(false);
  });
});

describe("getAgentIdFromSearchParam", () => {
  it("parses a valid agentId", () => {
    const searchParams = buildSearchParams("agentId=8");
    expect(getAgentIdFromSearchParam(searchParams)).toBe(8);
  });

  it("returns null when agentId is absent", () => {
    expect(getAgentIdFromSearchParam(buildSearchParams(""))).toBe(null);
  });

  it("returns null when agentId is not an integer", () => {
    const searchParams = buildSearchParams("agentId=not-a-number");
    expect(getAgentIdFromSearchParam(searchParams)).toBe(null);
  });

  it("returns null when agentId is empty", () => {
    const searchParams = buildSearchParams("agentId=");
    expect(getAgentIdFromSearchParam(searchParams)).toBe(null);
  });

  // Regression: parseInt accepted numeric prefixes like "12abc" as 12.
  it("returns null when agentId has a non-numeric suffix", () => {
    const searchParams = buildSearchParams("agentId=12abc");
    expect(getAgentIdFromSearchParam(searchParams)).toBe(null);
  });

  it("returns null for negative or decimal values", () => {
    expect(getAgentIdFromSearchParam(buildSearchParams("agentId=-3"))).toBe(
      null
    );
    expect(getAgentIdFromSearchParam(buildSearchParams("agentId=1.5"))).toBe(
      null
    );
  });

  it("returns null for values beyond the safe integer range", () => {
    const searchParams = buildSearchParams("agentId=99999999999999999999");
    expect(getAgentIdFromSearchParam(searchParams)).toBe(null);
  });

  it("reads the documented agentId param name", () => {
    expect(SEARCH_PARAM_NAMES.PERSONA_ID).toBe("agentId");
  });
});
