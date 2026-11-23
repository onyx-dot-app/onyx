import { fireEvent, render, screen } from "@tests/setup/test-utils";
import { OutputImageThumbnail } from "@/sections/output-panel/OutputTile";

test("an image thumbnail shows a new src after the previous src failed", () => {
  const view = render(
    <OutputImageThumbnail src="/old.png" fallback={<p>Fallback</p>} />
  );
  const oldImage = view.container.querySelector("img");
  expect(oldImage).not.toBeNull();
  fireEvent.error(oldImage!);
  expect(screen.getByText("Fallback")).toBeInTheDocument();

  view.rerender(
    <OutputImageThumbnail src="/new.png" fallback={<p>Fallback</p>} />
  );

  expect(screen.queryByText("Fallback")).not.toBeInTheDocument();
  expect(view.container.querySelector("img")).toHaveAttribute(
    "src",
    "/new.png"
  );
});
