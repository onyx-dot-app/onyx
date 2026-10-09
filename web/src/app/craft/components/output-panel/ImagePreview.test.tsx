import { fireEvent, render, screen } from "@tests/setup/test-utils";
import ImagePreview from "@/app/craft/components/output-panel/ImagePreview";

it("toggles the contrasting image background", () => {
  render(<ImagePreview src="data:image/png;base64,abc" fileName="image.png" />);
  const toggle = screen.getByRole("button", { name: "Contrast background" });
  const image = screen.getByRole("img");
  expect(toggle).toHaveAttribute("aria-pressed", "true");
  expect(image).toHaveClass("bg-background-neutral-inverted-04");
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-pressed", "false");
  expect(image).not.toHaveClass("bg-background-neutral-inverted-04");
});
