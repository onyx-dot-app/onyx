import { redirect } from "next/navigation";
import Page from "@/app/craft/v1/apps/page";

jest.mock("next/navigation", () => ({ redirect: jest.fn() }));

beforeEach(() => jest.clearAllMocks());

test("old Apps routes redirect to Plugins", async () => {
  await Page({ searchParams: Promise.resolve({}) });
  expect(redirect).toHaveBeenCalledWith("/craft/v1/plugins");
});

test("redirect preserves external-app connect intent and OAuth return values", async () => {
  await Page({
    searchParams: Promise.resolve({
      connect: "7",
      code: "oauth/code",
      state: "return state",
      tag: ["one", "two"],
      empty: undefined,
    }),
  });
  expect(redirect).toHaveBeenCalledWith(
    "/craft/v1/plugins?connect=7&code=oauth%2Fcode&state=return+state&tag=one&tag=two"
  );
});
