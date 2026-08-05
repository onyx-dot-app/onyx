import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import * as WebBrowser from "expo-web-browser";

import { documentTarget, openSource } from "@/chat/openSource";
import { toast } from "@/hooks/useToast";

import { makeSearchDoc } from "./fixtures";

jest.mock("expo-web-browser", () => ({
  openBrowserAsync: jest.fn(() => Promise.resolve()),
}));

jest.mock("@/hooks/useToast", () => ({
  toast: Object.assign(jest.fn(), {
    info: jest.fn(),
    error: jest.fn(),
    success: jest.fn(),
    warning: jest.fn(),
    dismiss: jest.fn(),
    clearAll: jest.fn(),
  }),
}));

beforeEach(() => {
  jest.clearAllMocks();
});

describe("documentTarget", () => {
  it("routes a linked doc to the browser", () => {
    expect(documentTarget(makeSearchDoc({ link: "https://a.com" }))).toEqual({
      kind: "browser",
      url: "https://a.com",
    });
  });

  it("routes a file doc (no link) to file", () => {
    expect(
      documentTarget(makeSearchDoc({ link: null, file_id: "f1" })),
    ).toEqual({ kind: "file", fileId: "f1" });
  });

  it("routes a doc with neither link nor file to none", () => {
    expect(
      documentTarget(makeSearchDoc({ link: null, file_id: null })),
    ).toEqual({ kind: "none" });
  });

  it("treats a non-http link as not browsable", () => {
    expect(
      documentTarget(makeSearchDoc({ link: "ftp://x", file_id: null })),
    ).toEqual({ kind: "none" });
  });
});

describe("openSource", () => {
  it("opens a linked doc in the in-app browser", () => {
    openSource(makeSearchDoc({ link: "https://a.com" }));
    expect(WebBrowser.openBrowserAsync).toHaveBeenCalledWith("https://a.com");
  });

  it("toasts for a file doc with no link", () => {
    openSource(makeSearchDoc({ link: null, file_id: "f1" }));
    expect(WebBrowser.openBrowserAsync).not.toHaveBeenCalled();
    expect(toast.info).toHaveBeenCalledTimes(1);
  });
});
