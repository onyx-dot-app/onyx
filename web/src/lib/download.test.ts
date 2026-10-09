/** @jest-environment jsdom */
import { downloadFile } from "@/lib/download";

it("downloads existing binary bytes and revokes their temporary URL", () => {
  jest.useFakeTimers();
  const blob = new Blob([new Uint8Array([0, 255])], {
    type: "application/pdf",
  });
  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;
  const createUrl = jest.fn(() => "blob:binary");
  const revokeUrl = jest.fn();
  URL.createObjectURL = createUrl;
  URL.revokeObjectURL = revokeUrl;
  const click = jest
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.href).toBe("blob:binary");
      expect(this.download).toBe("report.pdf");
      expect(document.body.contains(this)).toBe(true);
    });
  try {
    downloadFile("report.pdf", { content: blob });
    expect(createUrl).toHaveBeenCalledWith(blob);
    expect(click).toHaveBeenCalledTimes(1);
    expect(document.querySelector('a[href="blob:binary"]')).toBeNull();
    expect(revokeUrl).not.toHaveBeenCalled();
    jest.runAllTimers();
    expect(revokeUrl).toHaveBeenCalledWith("blob:binary");
  } finally {
    URL.createObjectURL = originalCreate;
    URL.revokeObjectURL = originalRevoke;
    jest.restoreAllMocks();
    jest.useRealTimers();
  }
});
