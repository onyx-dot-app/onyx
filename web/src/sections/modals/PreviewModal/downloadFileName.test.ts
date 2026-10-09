import {
  parseContentDispositionFileName,
  withMimeTypeExtension,
} from "@/sections/modals/PreviewModal/downloadFileName";

const PPTX_MIME_TYPE =
  "application/vnd.openxmlformats-officedocument.presentationml.presentation";

describe("parseContentDispositionFileName", () => {
  it("prefers the RFC 5987 name", () => {
    expect(
      parseContentDispositionFileName(
        "attachment; filename=\"R_sum_.docx\"; filename*=UTF-8''R%C3%A9sum%C3%A9.docx"
      )
    ).toBe("Résumé.docx");
  });

  it("falls back to the quoted name", () => {
    expect(
      parseContentDispositionFileName('attachment; filename="Q3 Deck.pptx"')
    ).toBe("Q3 Deck.pptx");
  });

  it("falls back to the quoted name when the encoded name is malformed", () => {
    expect(
      parseContentDispositionFileName(
        "attachment; filename=\"deck.pptx\"; filename*=UTF-8''%E0%A4%A"
      )
    ).toBe("deck.pptx");
  });

  it("reads an unquoted name", () => {
    expect(
      parseContentDispositionFileName("attachment; filename=logs.zip")
    ).toBe("logs.zip");
  });

  it("returns null without a name", () => {
    expect(parseContentDispositionFileName("attachment")).toBeNull();
    expect(parseContentDispositionFileName(null)).toBeNull();
  });
});

describe("withMimeTypeExtension", () => {
  it("appends the extension for the MIME type", () => {
    expect(withMimeTypeExtension("Q3 Deck", PPTX_MIME_TYPE)).toBe(
      "Q3 Deck.pptx"
    );
    expect(withMimeTypeExtension("Sales v1.2 data", "text/csv")).toBe(
      "Sales v1.2 data.csv"
    );
  });

  it("keeps an existing extension", () => {
    expect(withMimeTypeExtension("deck.pptx", "text/plain")).toBe("deck.pptx");
  });

  it("does not append an extension for unknown or generic types", () => {
    expect(withMimeTypeExtension("blob", "application/octet-stream")).toBe(
      "blob"
    );
    expect(withMimeTypeExtension("blob", "application/x-onyx-unknown")).toBe(
      "blob"
    );
  });
});
