import type { ReadonlyURLSearchParams } from "next/navigation";
import {
  SEARCH_PARAM_NAMES,
  shouldSendOnLoad,
  shouldSubmitOnLoad,
} from "./searchParams";

function makeSearchParams(query: string): ReadonlyURLSearchParams {
  return new URLSearchParams(query) as unknown as ReadonlyURLSearchParams;
}

describe("searchParams", () => {
  describe.each([
    [
      "shouldSubmitOnLoad",
      shouldSubmitOnLoad,
      SEARCH_PARAM_NAMES.SUBMIT_ON_LOAD,
    ],
    ["shouldSendOnLoad", shouldSendOnLoad, SEARCH_PARAM_NAMES.SEND_ON_LOAD],
  ])("%s", (_name, parse, param) => {
    it.each(["true", "1"])("is enabled by %p", (value) => {
      expect(parse(makeSearchParams(`${param}=${value}`))).toBe(true);
    });

    it.each(["false", "0", ""])("is not enabled by %p", (value) => {
      expect(parse(makeSearchParams(`${param}=${value}`))).toBe(false);
    });

    it("is not enabled when the param is absent", () => {
      expect(parse(makeSearchParams("user-prompt=hi"))).toBe(false);
    });

    it("is not enabled without search params", () => {
      expect(parse(null)).toBe(false);
    });
  });
});
