import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import Checkbox from "./Checkbox";

describe("Checkbox", () => {
  describe("Rendering", () => {
    test("renders unchecked by default", () => {
      const { container } = render(<Checkbox />);
      const checkbox = screen.getByRole("checkbox");
      const input = container.querySelector(
        'input[type="checkbox"]'
      ) as HTMLInputElement;
      expect(checkbox).toHaveAttribute("aria-checked", "false");
      expect(input).not.toBeChecked();
    });

    test("renders checked when checked prop is true", () => {
      const { container } = render(
        <Checkbox checked={true} onCheckedChange={() => {}} />
      );
      const checkbox = screen.getByRole("checkbox");
      const input = container.querySelector(
        'input[type="checkbox"]'
      ) as HTMLInputElement;
      expect(checkbox).toHaveAttribute("aria-checked", "true");
      expect(input).toBeChecked();
    });

    test("renders unchecked when checked prop is false", () => {
      const { container } = render(
        <Checkbox checked={false} onCheckedChange={() => {}} />
      );
      const checkbox = screen.getByRole("checkbox");
      const input = container.querySelector(
        'input[type="checkbox"]'
      ) as HTMLInputElement;
      expect(checkbox).toHaveAttribute("aria-checked", "false");
      expect(input).not.toBeChecked();
    });

    test("renders with defaultChecked", () => {
      const { container } = render(<Checkbox defaultChecked={true} />);
      const checkbox = screen.getByRole("checkbox");
      const input = container.querySelector(
        'input[type="checkbox"]'
      ) as HTMLInputElement;
      expect(checkbox).toHaveAttribute("aria-checked", "true");
      expect(input).toBeChecked();
    });

    test("applies custom className", () => {
      const { container } = render(<Checkbox className="custom-class" />);
      const visualCheckbox = container.querySelector(".custom-class");
      expect(visualCheckbox).toBeInTheDocument();
    });
  });

  describe("Controlled mode", () => {
    test("calls onCheckedChange when clicked", () => {
      const handleChange = jest.fn();
      render(<Checkbox checked={false} onCheckedChange={handleChange} />);
      const visualCheckbox = screen.getByRole("checkbox");
      fireEvent.click(visualCheckbox);
      expect(handleChange).toHaveBeenCalledWith(true);
    });

    test("does not change state when controlled", () => {
      const handleChange = jest.fn();
      const { container } = render(
        <Checkbox checked={false} onCheckedChange={handleChange} />
      );
      const visualCheckbox = screen.getByRole("checkbox");
      const input = container.querySelector(
        'input[type="checkbox"]'
      ) as HTMLInputElement;
      fireEvent.click(visualCheckbox);
      expect(input).not.toBeChecked(); // Should not change without parent updating prop
    });

    test("updates when checked prop changes", () => {
      const { rerender, container } = render(
        <Checkbox checked={false} onCheckedChange={() => {}} />
      );
      let checkbox = screen.getByRole("checkbox");
      let input = container.querySelector(
        'input[type="checkbox"]'
      ) as HTMLInputElement;
      expect(checkbox).toHaveAttribute("aria-checked", "false");
      expect(input).not.toBeChecked();

      rerender(<Checkbox checked={true} onCheckedChange={() => {}} />);
      checkbox = screen.getByRole("checkbox");
      input = container.querySelector(
        'input[type="checkbox"]'
      ) as HTMLInputElement;
      expect(checkbox).toHaveAttribute("aria-checked", "true");
      expect(input).toBeChecked();
    });
  });

  describe("Uncontrolled mode", () => {
    test("toggles state and calls onCheckedChange when clicked", () => {
      const handleChange = jest.fn();
      const { container } = render(<Checkbox onCheckedChange={handleChange} />);
      const visualCheckbox = screen.getByRole("checkbox");
      const input = container.querySelector(
        'input[type="checkbox"]'
      ) as HTMLInputElement;

      expect(visualCheckbox).toHaveAttribute("aria-checked", "false");
      expect(input).not.toBeChecked();
      fireEvent.click(visualCheckbox);
      expect(visualCheckbox).toHaveAttribute("aria-checked", "true");
      expect(input).toBeChecked();
      expect(handleChange).toHaveBeenCalledWith(true);

      fireEvent.click(visualCheckbox);
      expect(visualCheckbox).toHaveAttribute("aria-checked", "false");
      expect(input).not.toBeChecked();
      expect(handleChange).toHaveBeenCalledWith(false);
    });
  });

  describe("Indeterminate state", () => {
    test("sets correct aria-checked values for all states", () => {
      const { rerender, container } = render(
        <Checkbox checked={false} onCheckedChange={() => {}} />
      );
      let checkbox = screen.getByRole("checkbox");
      expect(checkbox).toHaveAttribute("aria-checked", "false");

      rerender(<Checkbox checked={true} onCheckedChange={() => {}} />);
      checkbox = screen.getByRole("checkbox");
      expect(checkbox).toHaveAttribute("aria-checked", "true");

      rerender(<Checkbox indeterminate={true} />);
      checkbox = screen.getByRole("checkbox");
      const input = container.querySelector(
        'input[type="checkbox"]'
      ) as HTMLInputElement;
      expect(checkbox).toHaveAttribute("aria-checked", "mixed");
      expect(input.indeterminate).toBe(true);
    });
  });

  describe("Disabled state", () => {
    test("sets disabled attribute and prevents interaction", () => {
      const handleChange = jest.fn();
      const { container } = render(
        <Checkbox disabled={true} onCheckedChange={handleChange} />
      );
      const visualCheckbox = screen.getByRole("checkbox");
      const input = container.querySelector(
        'input[type="checkbox"]'
      ) as HTMLInputElement;

      expect(input).toBeDisabled();
      expect(input).not.toBeChecked();

      fireEvent.click(visualCheckbox);
      expect(input).not.toBeChecked();
      expect(handleChange).not.toHaveBeenCalled();
    });
  });

  describe("Keyboard interaction", () => {
    test("toggles when spacebar is pressed on visual checkbox", () => {
      const { container } = render(<Checkbox />);
      const visualCheckbox = screen.getByRole("checkbox");
      const input = container.querySelector(
        'input[type="checkbox"]'
      ) as HTMLInputElement;

      visualCheckbox.focus();
      expect(input).not.toBeChecked();

      fireEvent.keyDown(visualCheckbox, { key: " ", code: "Space" });
      expect(input).toBeChecked();
    });

    test("toggles when Enter is pressed on visual checkbox", () => {
      const { container } = render(<Checkbox />);
      const visualCheckbox = screen.getByRole("checkbox");
      const input = container.querySelector(
        'input[type="checkbox"]'
      ) as HTMLInputElement;

      visualCheckbox.focus();
      expect(input).not.toBeChecked();

      fireEvent.keyDown(visualCheckbox, { key: "Enter", code: "Enter" });
      expect(input).toBeChecked();
    });
  });

  describe("onChange handler", () => {
    test("calls onChange when provided", () => {
      const handleChange = jest.fn();
      render(<Checkbox onChange={handleChange} />);
      const checkbox = screen.getByRole("checkbox");

      fireEvent.click(checkbox);
      expect(handleChange).toHaveBeenCalled();
    });

    test("calls both onChange and onCheckedChange", () => {
      const handleChange = jest.fn();
      const handleCheckedChange = jest.fn();
      render(
        <Checkbox
          onChange={handleChange}
          onCheckedChange={handleCheckedChange}
        />
      );
      const checkbox = screen.getByRole("checkbox");

      fireEvent.click(checkbox);
      expect(handleChange).toHaveBeenCalled();
      expect(handleCheckedChange).toHaveBeenCalledWith(true);
    });
  });

  describe("Ref forwarding", () => {
    test("forwards ref to input element", () => {
      const ref = React.createRef<HTMLInputElement>();
      render(<Checkbox ref={ref} />);
      expect(ref.current).toBeInstanceOf(HTMLInputElement);
      expect(ref.current?.type).toBe("checkbox");
    });
  });

  describe("Accessibility", () => {
    test("has role checkbox", () => {
      render(<Checkbox />);
      const checkbox = screen.getByRole("checkbox");
      expect(checkbox).toBeInTheDocument();
    });

    test("supports aria-label", () => {
      render(<Checkbox aria-label="Accept terms" />);
      const checkbox = screen.getByRole("checkbox");
      expect(checkbox).toHaveAttribute("aria-label", "Accept terms");
    });

    test("supports aria-labelledby", () => {
      render(
        <div>
          <span id="checkbox-label">Accept terms</span>
          <Checkbox aria-labelledby="checkbox-label" />
        </div>
      );
      const checkbox = screen.getByRole("checkbox");
      expect(checkbox).toHaveAttribute("aria-labelledby", "checkbox-label");
    });
  });
});
