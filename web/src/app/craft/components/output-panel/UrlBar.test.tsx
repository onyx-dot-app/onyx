import React from "react";
import { fireEvent } from "@testing-library/react";
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
    (copyText as jest.Mock).mockReset();
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
    const textWrapper = screen.getByTestId("url-text-wrapper");
    const urlPill = screen.getByTestId("url-bar-pill");
    const openButton = screen.getByRole("button", {
      name: "open in a new tab",
    });

    expect(urlText.tagName).toBe("P");
    expect(urlText).toHaveClass("truncate");
    expect(copyButton).toHaveClass(
      "block",
      "w-full",
      "min-w-0",
      "cursor-pointer"
    );
    expect(textWrapper).toHaveClass("min-w-0", "flex-1", "overflow-hidden");
    expect(urlPill).toHaveClass("min-w-0", "flex-1");
    expect(openButton).toHaveAttribute("data-copy-state", "idle");
    expect(
      screen.getByRole("button", { name: "Share webapp" })
    ).toBeInTheDocument();

    await user.hover(copyButton);
    await waitFor(() => {
      expect(screen.getAllByText(longPreviewUrl).length).toBeGreaterThan(1);
    });

    await user.click(copyButton);
    expect(copyText).toHaveBeenCalledWith(longPreviewUrl);
    await waitFor(() => {
      expect(openButton).toHaveAttribute("data-copy-state", "copied");
    });
    const copiedIcon = openButton.querySelector("svg");
    expect(copiedIcon).toBeInTheDocument();
    fireEvent.animationEnd(copiedIcon!);
    await waitFor(() => {
      expect(openButton).toHaveAttribute("data-copy-state", "idle");
    });
    expect(
      screen.getByRole("button", { name: "open in a new tab" })
    ).toBeInTheDocument();

    await user.hover(openButton);
    await waitFor(() => {
      expect(screen.getAllByText("open in a new tab").length).toBeGreaterThan(
        0
      );
    });
    expect(screen.queryByText("Copied URL")).not.toBeInTheDocument();
  });

  test("resets copy feedback when the displayed URL changes", async () => {
    const user = setupUser();
    const firstPreviewUrl = "https://craft-preview.onyx.app/sessions/first";
    const secondPreviewUrl = "https://craft-preview.onyx.app/sessions/second";
    const { rerender } = render(
      <UrlBar displayUrl={firstPreviewUrl} previewUrl={firstPreviewUrl} />
    );

    await user.click(
      screen.getByRole("button", {
        name: `Copy URL: ${firstPreviewUrl}`,
      })
    );
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "open in a new tab" })
      ).toHaveAttribute("data-copy-state", "copied");
    });

    rerender(
      <UrlBar displayUrl={secondPreviewUrl} previewUrl={secondPreviewUrl} />
    );

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "open in a new tab" })
      ).toHaveAttribute("data-copy-state", "idle");
    });
    expect(
      screen.getByRole("button", {
        name: `Copy URL: ${secondPreviewUrl}`,
      })
    ).toBeInTheDocument();
  });

  test.each(["no-sandbox://", "artifacts://"])(
    "does not copy internal display URL %s",
    async (internalUrl) => {
      render(<UrlBar displayUrl={internalUrl} />);

      expect(screen.getByText(internalUrl)).toHaveClass("truncate");
      expect(
        screen.queryByRole("button", { name: `Copy URL: ${internalUrl}` })
      ).not.toBeInTheDocument();
      expect(copyText).not.toHaveBeenCalled();
    }
  );
});
