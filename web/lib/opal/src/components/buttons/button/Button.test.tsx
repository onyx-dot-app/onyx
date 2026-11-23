import { render, screen } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import { Button } from "@opal/components";
import { SvgDownload } from "@opal/icons";

describe("Button download link", () => {
  it("renders one link that downloads the file under its name", () => {
    render(
      <Button
        href="/api/chat/file/file-1"
        download="report.csv"
        icon={SvgDownload}
      >
        Download
      </Button>
    );

    const link = screen.getByRole("link", { name: "Download" });
    expect(link.tagName).toBe("A");
    expect(link).toHaveAttribute("href", "/api/chat/file/file-1");
    expect(link).toHaveAttribute("download", "report.csv");
    expect(link).toHaveClass("interactive", "interactive-container");
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getAllByRole("link")).toHaveLength(1);
  });

  it("keeps the server's file name with download={true}", () => {
    render(
      <Button href="/api/chat/file/file-1" download icon={SvgDownload}>
        Download
      </Button>
    );

    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute(
      "download",
      ""
    );
  });

  it("takes one tab stop", async () => {
    const user = userEvent.setup();
    render(
      <Button
        href="/api/chat/file/file-1"
        download="report.csv"
        icon={SvgDownload}
        aria-label="Download"
      />
    );

    await user.tab();
    expect(screen.getByRole("link", { name: "Download" })).toHaveFocus();
    await user.tab();
    expect(document.body).toHaveFocus();
  });

  it("disabled, has no URL, takes no focus and does not download", async () => {
    const user = userEvent.setup();
    render(
      <Button href="/api/chat/file/file-1" download="report.csv" disabled>
        Download
      </Button>
    );

    expect(screen.queryByRole("link")).toBeNull();
    const control = screen.getByRole("button", { name: "Download" });
    expect(control).toHaveAttribute("aria-disabled", "true");
    expect(control).not.toHaveAttribute("href");
    expect(control).not.toHaveAttribute("download");
    await user.tab();
    expect(control).not.toHaveFocus();
  });
});
