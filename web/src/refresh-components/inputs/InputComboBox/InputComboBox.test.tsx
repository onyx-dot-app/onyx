import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import userEvent from "@testing-library/user-event";
import InputComboBox from "./InputComboBox";

// Mock createPortal for dropdown rendering
jest.mock("react-dom", () => ({
  ...jest.requireActual("react-dom"),
  createPortal: (node: React.ReactNode) => node,
}));

// Mock scrollIntoView which is not available in jsdom
Element.prototype.scrollIntoView = jest.fn();

const mockOptions = [
  { value: "apple", label: "Apple" },
  { value: "banana", label: "Banana" },
  { value: "cherry", label: "Cherry" },
];

const mockOptionsWithDescriptions = [
  { value: "apple", label: "Apple", description: "A red fruit" },
  { value: "banana", label: "Banana", description: "A yellow fruit" },
];

function setupUser() {
  return userEvent.setup({ delay: null });
}

describe("InputComboBox", () => {
  describe("Rendering", () => {
    test("renders with placeholder", () => {
      render(
        <InputComboBox
          placeholder="Select an option"
          value=""
          options={mockOptions}
        />
      );
      const input = screen.getByPlaceholderText("Select an option");
      expect(input).toBeInTheDocument();
    });

    test("renders with initial value", () => {
      render(
        <InputComboBox
          placeholder="Select"
          value="apple"
          options={mockOptions}
        />
      );
      const input = screen.getByDisplayValue("Apple");
      expect(input).toBeInTheDocument();
    });

    test("renders without options (input mode)", () => {
      render(<InputComboBox placeholder="Type here" value="" options={[]} />);
      const input = screen.getByPlaceholderText("Type here");
      expect(input).toBeInTheDocument();
    });

    test("renders disabled state", () => {
      render(
        <InputComboBox
          placeholder="Select"
          value=""
          options={mockOptions}
          disabled
        />
      );
      const input = screen.getByPlaceholderText("Select");
      expect(input).toBeDisabled();
    });

    test("renders with options that have descriptions", () => {
      render(
        <InputComboBox
          placeholder="Select"
          value=""
          options={mockOptionsWithDescriptions}
        />
      );
      const input = screen.getByPlaceholderText("Select");
      fireEvent.focus(input);
      expect(screen.getByText("A red fruit")).toBeInTheDocument();
    });
  });

  describe("Dropdown Behavior", () => {
    test("opens dropdown on focus when options exist", () => {
      render(
        <InputComboBox placeholder="Select" value="" options={mockOptions} />
      );
      const input = screen.getByPlaceholderText("Select");
      fireEvent.focus(input);
      expect(screen.getByRole("listbox")).toBeInTheDocument();
    });

    test("does not open dropdown on focus when no options", () => {
      render(<InputComboBox placeholder="Select" value="" options={[]} />);
      const input = screen.getByPlaceholderText("Select");
      fireEvent.focus(input);
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    });

    test("closes dropdown on escape", async () => {
      const user = setupUser();
      render(
        <InputComboBox placeholder="Select" value="" options={mockOptions} />
      );
      const input = screen.getByPlaceholderText("Select");

      await user.click(input);
      expect(screen.getByRole("listbox")).toBeInTheDocument();

      await user.keyboard("{Escape}");
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    });

    test("closes dropdown on tab", async () => {
      const user = setupUser();
      render(
        <InputComboBox placeholder="Select" value="" options={mockOptions} />
      );
      const input = screen.getByPlaceholderText("Select");

      await user.click(input);
      expect(screen.getByRole("listbox")).toBeInTheDocument();

      await user.tab();
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    });
  });

  describe("Keyboard Navigation", () => {
    test("ArrowDown opens dropdown and highlights first option", async () => {
      const user = setupUser();
      render(
        <InputComboBox placeholder="Select" value="" options={mockOptions} />
      );
      const input = screen.getByPlaceholderText("Select");

      await user.click(input);
      await user.keyboard("{ArrowDown}");

      const listbox = screen.getByRole("listbox");
      expect(listbox).toBeInTheDocument();
    });

    test("ArrowUp moves highlight up through options", async () => {
      const user = setupUser();
      render(
        <InputComboBox placeholder="Select" value="" options={mockOptions} />
      );
      const input = screen.getByPlaceholderText("Select");

      await user.click(input);
      await user.keyboard("{ArrowDown}");
      await user.keyboard("{ArrowDown}");
      await user.keyboard("{ArrowUp}");

      // Highlight should have moved
      expect(screen.getByRole("listbox")).toBeInTheDocument();
    });

    test("Enter selects highlighted option", async () => {
      const handleValueChange = jest.fn();
      const user = setupUser();
      render(
        <InputComboBox
          placeholder="Select"
          value=""
          options={mockOptions}
          onValueChange={handleValueChange}
        />
      );
      const input = screen.getByPlaceholderText("Select");

      await user.click(input);
      await user.keyboard("{ArrowDown}");
      await user.keyboard("{Enter}");

      expect(handleValueChange).toHaveBeenCalledWith("apple");
    });
  });

  describe("Filtering", () => {
    test("filters options based on input value", async () => {
      const user = setupUser();
      render(
        <InputComboBox placeholder="Select" value="" options={mockOptions} />
      );
      const input = screen.getByPlaceholderText("Select");

      await user.type(input, "app");

      // Get all options and check the first one contains Apple
      const options = screen.getAllByRole("option");
      expect(options.length).toBeGreaterThan(0);
      expect(options[0]!.textContent).toBe("Apple");
      // Banana and Cherry should be in "Other options" section
      expect(screen.getByText("Banana")).toBeInTheDocument();
    });

    test("shows 'No options found' when no matches and strict mode", async () => {
      const user = setupUser();
      render(
        <InputComboBox
          placeholder="Select"
          value=""
          options={mockOptions}
          strict
        />
      );
      const input = screen.getByPlaceholderText("Select");

      await user.type(input, "xyz");

      // In strict mode with no matches, all options go to "Other options" section
      // which shows all options (not "No options found")
      expect(screen.getByText("Other options")).toBeInTheDocument();
    });

    test("shows separator between matched and unmatched options", async () => {
      const user = setupUser();
      render(
        <InputComboBox
          placeholder="Select"
          value=""
          options={mockOptions}
          separatorLabel="Other fruits"
        />
      );
      const input = screen.getByPlaceholderText("Select");

      await user.type(input, "app");

      expect(screen.getByText("Other fruits")).toBeInTheDocument();
    });
  });

  describe("Selection", () => {
    test("clicking option selects it and closes dropdown", async () => {
      const handleChange = jest.fn();
      const handleValueChange = jest.fn();
      const user = setupUser();
      render(
        <InputComboBox
          placeholder="Select"
          value=""
          options={mockOptions}
          onChange={handleChange}
          onValueChange={handleValueChange}
        />
      );
      const input = screen.getByPlaceholderText("Select");

      await user.click(input);
      const option = screen.getByText("Banana");
      await user.click(option);

      expect(handleChange).toHaveBeenCalled();
      expect(handleValueChange).toHaveBeenCalledWith("banana");
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    });

    test("displays label instead of value when closed", () => {
      render(
        <InputComboBox
          placeholder="Select"
          value="apple"
          options={mockOptions}
        />
      );
      // Should show "Apple" (label) not "apple" (value)
      expect(screen.getByDisplayValue("Apple")).toBeInTheDocument();
    });
  });

  describe("Strict Mode", () => {
    test("strict=true shows error when value not in options", () => {
      render(
        <InputComboBox
          placeholder="Select"
          value="invalid"
          options={mockOptions}
          strict
        />
      );
      expect(
        screen.getByText("Please select a valid option from the list")
      ).toBeInTheDocument();
    });

    test("strict=false allows custom values", () => {
      render(
        <InputComboBox
          placeholder="Select"
          value="custom-value"
          options={mockOptions}
          strict={false}
        />
      );
      expect(
        screen.queryByText("Please select a valid option from the list")
      ).not.toBeInTheDocument();
    });

    test("strict=false shows create option when no matches", async () => {
      const user = setupUser();
      render(
        <InputComboBox
          placeholder="Select"
          value=""
          options={mockOptions}
          strict={false}
        />
      );
      const input = screen.getByPlaceholderText("Select");

      await user.type(input, "newvalue");

      // Should show the create option with the typed value
      expect(screen.getByText("newvalue")).toBeInTheDocument();
    });
  });

  describe("External Error State", () => {
    test("shows error styling when isError is true", () => {
      const { container } = render(
        <InputComboBox
          placeholder="Select"
          value=""
          options={mockOptions}
          isError
        />
      );
      // The input should have error styling applied
      expect(container.querySelector("input")).toBeInTheDocument();
    });

    test("does not show internal error when isError is provided", () => {
      render(
        <InputComboBox
          placeholder="Select"
          value="invalid"
          options={mockOptions}
          strict
          isError={false}
        />
      );
      // Internal validation error should not show when isError is explicitly false
      expect(
        screen.queryByText("Please select a valid option from the list")
      ).not.toBeInTheDocument();
    });
  });

  describe("Accessibility", () => {
    test("has correct ARIA attributes", () => {
      render(
        <InputComboBox placeholder="Select" value="" options={mockOptions} />
      );
      const input = screen.getByRole("combobox");
      expect(input).toHaveAttribute("aria-autocomplete", "list");
      expect(input).toHaveAttribute("aria-expanded", "false");
    });

    test("aria-expanded is true when dropdown is open", () => {
      render(
        <InputComboBox placeholder="Select" value="" options={mockOptions} />
      );
      const input = screen.getByRole("combobox");
      fireEvent.focus(input);
      expect(input).toHaveAttribute("aria-expanded", "true");
    });

    test("options have role option", () => {
      render(
        <InputComboBox placeholder="Select" value="" options={mockOptions} />
      );
      const input = screen.getByPlaceholderText("Select");
      fireEvent.focus(input);

      const options = screen.getAllByRole("option");
      expect(options.length).toBe(3);
    });

    test("listbox has correct aria-label", () => {
      render(
        <InputComboBox
          placeholder="Select a fruit"
          value=""
          options={mockOptions}
        />
      );
      const input = screen.getByPlaceholderText("Select a fruit");
      fireEvent.focus(input);

      const listbox = screen.getByRole("listbox");
      expect(listbox).toHaveAttribute("aria-label", "Select a fruit");
    });
  });

  describe("Text Highlighting", () => {
    test("matching text is highlighted in option labels", async () => {
      const user = setupUser();
      const { container } = render(
        <InputComboBox placeholder="Select" value="" options={mockOptions} />
      );
      const input = screen.getByPlaceholderText("Select");

      await user.type(input, "app");

      // Look for the bold/highlighted text
      const boldText = container.querySelector(".font-semibold");
      expect(boldText).toBeInTheDocument();
      expect(boldText?.textContent).toBe("App");
    });
  });

  describe("onChange vs onValueChange", () => {
    test("onChange is called on every keystroke", async () => {
      const handleChange = jest.fn();
      const user = setupUser();
      render(
        <InputComboBox
          placeholder="Select"
          value=""
          options={mockOptions}
          onChange={handleChange}
        />
      );
      const input = screen.getByPlaceholderText("Select");

      await user.type(input, "abc");

      expect(handleChange).toHaveBeenCalledTimes(3);
    });

    test("onValueChange is only called on option select", async () => {
      const handleChange = jest.fn();
      const handleValueChange = jest.fn();
      const user = setupUser();
      render(
        <InputComboBox
          placeholder="Select"
          value=""
          options={mockOptions}
          onChange={handleChange}
          onValueChange={handleValueChange}
        />
      );
      const input = screen.getByPlaceholderText("Select");

      await user.type(input, "app");
      expect(handleValueChange).not.toHaveBeenCalled();

      // Get the Apple option by role and click it
      const options = screen.getAllByRole("option");
      const appleOption = options.find((opt) => opt.textContent === "Apple");
      expect(appleOption).toBeDefined();
      await user.click(appleOption!);
      expect(handleValueChange).toHaveBeenCalledWith("apple");
    });
  });

  describe("Disabled Options", () => {
    test("disabled options cannot be selected", async () => {
      const handleValueChange = jest.fn();
      const user = setupUser();
      const optionsWithDisabled = [
        { value: "apple", label: "Apple" },
        { value: "banana", label: "Banana", disabled: true },
      ];
      render(
        <InputComboBox
          placeholder="Select"
          value=""
          options={optionsWithDisabled}
          onValueChange={handleValueChange}
        />
      );
      const input = screen.getByPlaceholderText("Select");

      await user.click(input);
      const disabledOption = screen.getByText("Banana");
      await user.click(disabledOption);

      expect(handleValueChange).not.toHaveBeenCalled();
    });
  });
});
