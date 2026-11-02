import { render, screen } from "@tests/setup/test-utils";
import { Tag, type TagSize } from "@opal/components";

describe("Tag", () => {
  it.each(["sm", "md", "20", "24"] as TagSize[])(
    "renders size %s on the root",
    (size) => {
      render(
        <Tag title="Indexing" color="blue" variant="status" size={size} />
      );

      const root = screen.getByText("Indexing").closest(".opal-auxiliary-tag");
      expect(root).toHaveAttribute("data-size", size);
    }
  );
});
