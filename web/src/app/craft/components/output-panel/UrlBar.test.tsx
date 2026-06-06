import React from "react";
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { copyText } from "@opal/utils";
import UrlBar from "./UrlBar";

jest.mock("@opal/utils", () => {
  const actual = jest.requireActual("@opal/utils");
  return {
    ...actual,
    copyText: jest.fn(),
  };
});

describe("UrlBar", () => {
  beforeEach(() => {
    (copyText as jest.Mock).mockResolvedValue(undefined);
  });

  test("contains long preview URLs inside the URL bar and copies them", async () => {
    const user = setupUser();
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
    const copyButton = screen.getByRole("button", {
      name: `Copy URL: ${longPreviewUrl}`,
    });
    const textWrapper = urlText.parentElement;
    const urlPill = textWrapper?.parentElement?.parentElement;

    expect(urlText.tagName).toBe("P");
    expect(urlText).toHaveClass("truncate");
    expect(copyButton).toHaveClass("cursor-pointer");
    expect(textWrapper).toHaveClass("block", "w-full", "min-w-0");
    expect(textWrapper?.parentElement).toHaveClass(
      "min-w-0",
      "flex-1",
      "overflow-hidden"
    );
    expect(urlPill).toHaveClass("min-w-0", "flex-1");
    expect(
      screen.getByRole("button", { name: "Share webapp" })
    ).toBeInTheDocument();

    await user.hover(copyButton);
    await waitFor(() => {
      expect(screen.getAllByText(longPreviewUrl).length).toBeGreaterThan(1);
    });

    await user.click(copyButton);
    expect(copyText).toHaveBeenCalledWith(longPreviewUrl);
    expect(
      screen.getByRole("button", { name: "Copied URL; open in a new tab" })
    ).toBeInTheDocument();
  });
});
