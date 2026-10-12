import { fireEvent, render, screen } from "@tests/setup/test-utils";
import ImagePreview from "@/app/craft/components/output-panel/ImagePreview";

// Image identity and local display preferences
it("resets only image load state when replacing a failed source", () => {
  const { rerender } = render(
    <ImagePreview src="first.png" fileName="first.png" />
  );
  const image = screen.getByRole("img");
  fireEvent.load(image);
  fireEvent.click(screen.getByRole("button", { name: "Contrast background" }));
  fireEvent.error(image);
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  rerender(<ImagePreview src="replacement.png" fileName="replacement.png" />);
  const replacement = screen.getByRole("img");
  expect(replacement).toHaveClass("opacity-0");
  expect(
    screen.getByRole("button", { name: "Contrast background" })
  ).toHaveAttribute("aria-pressed", "false");
  fireEvent.load(replacement);
  expect(replacement).toHaveClass("opacity-100");
});

// Preview lifetime and rendering.
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
