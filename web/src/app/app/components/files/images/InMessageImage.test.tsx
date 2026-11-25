import { render, screen, userEvent } from "@tests/setup/test-utils";
import { InMessageImage } from "@/app/app/components/files/images/InMessageImage";
import { GALLERY_ROOT_ATTR } from "@/app/app/components/files/images/gallery";

function renderAnswer(ids: string[]) {
  return render(
    <div {...{ [GALLERY_ROOT_ATTR]: "" }}>
      {ids.map((id) => (
        <InMessageImage key={id} fileId={id} />
      ))}
    </div>
  );
}

function fullImageSrc(): string | null {
  return (
    screen.getByRole("dialog").querySelector("img")?.getAttribute("src") ?? null
  );
}

describe("full image gallery", () => {
  test("steps through the images of one answer and wraps at the end", async () => {
    const user = userEvent.setup();
    renderAnswer(["a", "b", "c"]);

    await user.click(
      screen.getAllByRole("button", { name: "View the full image" })[1]!
    );
    expect(fullImageSrc()).toBe("/api/chat/file/b");
    expect(screen.getByText("2 / 3")).toBeInTheDocument();

    await user.keyboard("{ArrowRight}");
    expect(fullImageSrc()).toBe("/api/chat/file/c");

    await user.keyboard("{ArrowRight}");
    expect(fullImageSrc()).toBe("/api/chat/file/a");

    await user.keyboard("{ArrowLeft}");
    expect(fullImageSrc()).toBe("/api/chat/file/c");

    await user.click(screen.getByRole("button", { name: "Previous image" }));
    expect(fullImageSrc()).toBe("/api/chat/file/b");
  });

  test("shows no navigation for a single image", async () => {
    const user = userEvent.setup();
    renderAnswer(["a"]);

    await user.click(
      screen.getByRole("button", { name: "View the full image" })
    );
    expect(
      screen.queryByRole("button", { name: "Next image" })
    ).not.toBeInTheDocument();
    await user.keyboard("{ArrowRight}");
    expect(fullImageSrc()).toBe("/api/chat/file/a");
  });

  test("flips the arrow keys in right-to-left layouts", async () => {
    const user = userEvent.setup();
    document.documentElement.dir = "rtl";
    try {
      renderAnswer(["a", "b", "c"]);
      await user.click(
        screen.getAllByRole("button", { name: "View the full image" })[1]!
      );
      await user.keyboard("{ArrowLeft}");
      expect(fullImageSrc()).toBe("/api/chat/file/c");
      await user.keyboard("{ArrowRight}");
      expect(fullImageSrc()).toBe("/api/chat/file/b");
    } finally {
      document.documentElement.dir = "";
    }
  });

  test("keeps the opened image's own alt text", async () => {
    const user = userEvent.setup();
    renderAnswer(["a", "b"]);
    await user.click(
      screen.getAllByRole("button", { name: "View the full image" })[0]!
    );
    expect(screen.getByRole("dialog").querySelector("img")).toHaveAttribute(
      "alt",
      "Chat attachment"
    );
  });
});
