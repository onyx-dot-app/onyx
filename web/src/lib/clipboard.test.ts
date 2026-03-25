import { getPastedFilesIfNoText } from "./clipboard";

type MockClipboardData = Parameters<typeof getPastedFilesIfNoText>[0];

function makeClipboardData({
  textPlain = "",
  text = "",
  files = [],
}: {
  textPlain?: string;
  text?: string;
  files?: File[];
}): MockClipboardData {
  return {
    items: files.map((file) => ({
      kind: "file",
      getAsFile: () => file,
    })),
    getData: (format: string) => {
      if (format === "text/plain") {
        return textPlain;
      }

      if (format === "text") {
        return text;
      }

      return "";
    },
  };
}

describe("getPastedFilesIfNoText", () => {
  it("prefers plain text over pasted files when both are present", () => {
    const imageFile = new File(["slide preview"], "slide.png", {
      type: "image/png",
    });

    expect(
      getPastedFilesIfNoText(
        makeClipboardData({
          textPlain: "Welcome to PowerPoint for Mac",
          files: [imageFile],
        })
      )
    ).toEqual([]);
  });

  it("falls back to text data when text/plain is empty", () => {
    const imageFile = new File(["slide preview"], "slide.png", {
      type: "image/png",
    });

    expect(
      getPastedFilesIfNoText(
        makeClipboardData({
          text: "Welcome to PowerPoint for Mac",
          files: [imageFile],
        })
      )
    ).toEqual([]);
  });

  it("still returns files for image-only pastes", () => {
    const imageFile = new File(["slide preview"], "slide.png", {
      type: "image/png",
    });

    expect(
      getPastedFilesIfNoText(makeClipboardData({ files: [imageFile] }))
    ).toEqual([imageFile]);
  });

  it("ignores whitespace-only text and keeps file pastes working", () => {
    const imageFile = new File(["slide preview"], "slide.png", {
      type: "image/png",
    });

    expect(
      getPastedFilesIfNoText(
        makeClipboardData({
          textPlain: "   ",
          text: "\n",
          files: [imageFile],
        })
      )
    ).toEqual([imageFile]);
  });
});
