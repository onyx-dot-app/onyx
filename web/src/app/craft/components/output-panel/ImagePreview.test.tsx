import { fireEvent, render, screen } from "@tests/setup/test-utils";
import ImagePreview from "@/app/craft/components/output-panel/ImagePreview";

// Image identity
it("resets image load state when replacing a failed source", () => {
  const { rerender } = render(
    <ImagePreview src="first.png" fileName="first.png" />
  );
  const image = screen.getByRole("img");
  fireEvent.load(image);
  fireEvent.error(image);
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  rerender(<ImagePreview src="replacement.png" fileName="replacement.png" />);
  const replacement = screen.getByRole("img");
  expect(replacement).toHaveClass("opacity-0");
  fireEvent.load(replacement);
  expect(replacement).toHaveClass("opacity-100");
});
