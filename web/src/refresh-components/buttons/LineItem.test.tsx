import { render, screen } from "@testing-library/react";
import LineItem from "@/refresh-components/buttons/LineItem";

describe("LineItem", () => {
  it("shows the appropriate cursor for its interaction state", () => {
    const { container, rerender } = render(
      <LineItem>Interactive item</LineItem>
    );

    expect(screen.getByRole("button")).toHaveClass("cursor-pointer");

    rerender(<LineItem disabled>Disabled item</LineItem>);

    expect(screen.getByRole("button")).toHaveClass("cursor-not-allowed");
    expect(screen.getByRole("button")).not.toHaveClass("cursor-pointer");

    rerender(<LineItem interactive={false}>Static item</LineItem>);

    expect(container.firstElementChild).not.toHaveClass(
      "cursor-pointer",
      "cursor-not-allowed"
    );
  });
});
