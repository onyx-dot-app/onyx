import React from "react";
import { render, screen } from "@tests/setup/test-utils";
import UrlBar from "./UrlBar";

describe("UrlBar", () => {
  test("contains long preview URLs inside the URL bar", () => {
    const longPreviewUrl =
      "https://craft-preview.onyx.app/sessions/session-with-a-very-long-id/apps/generated-webapp/routes/deeply/nested/path/with/an-unbroken-segment-that-would-otherwise-overflow-the-url-bar?query=another-unbroken-value-that-keeps-going";

    render(
      <UrlBar
        displayUrl={longPreviewUrl}
        previewUrl={longPreviewUrl}
        showNavigation
        canGoBack
        canGoForward
        onBack={jest.fn()}
        onForward={jest.fn()}
        onRefresh={jest.fn()}
        sessionId="session-with-a-very-long-id"
      />
    );

    const urlText = screen.getByText(longPreviewUrl);
    const textWrapper = urlText.parentElement;
    const urlPill = textWrapper?.parentElement;

    expect(urlText.tagName).toBe("P");
    expect(urlText).toHaveClass("truncate");
    expect(urlText).toHaveAttribute("title", longPreviewUrl);
    expect(textWrapper).toHaveClass("min-w-0", "flex-1", "overflow-hidden");
    expect(urlPill).toHaveClass("min-w-0", "flex-1");
    expect(
      screen.getByRole("button", { name: "Share webapp" })
    ).toBeInTheDocument();
  });
});
