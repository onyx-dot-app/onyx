import React from "react";
import { render, screen, waitFor } from "@tests/setup/test-utils";
import "@testing-library/jest-dom";
import userEvent from "@testing-library/user-event";
import { Formik } from "formik";
import { InputMultiSelectField } from "./InputMultiSelectField";
import { InputMultiComboBoxField } from "./InputMultiComboBoxField";

// Mock createPortal for dropdown rendering
jest.mock("react-dom", () => ({
  ...jest.requireActual("react-dom"),
  createPortal: (node: React.ReactNode) => node,
}));

// Mock scrollIntoView which is not available in jsdom
Element.prototype.scrollIntoView = jest.fn();

const options = [
  { value: "apple", title: "Apple" },
  { value: "banana", title: "Banana" },
];

interface FruitForm {
  fruits: string[];
}

function requireOne(values: FruitForm) {
  return values.fruits.length === 0 ? { fruits: "Pick at least one" } : {};
}

const emptyForm: FruitForm = { fruits: [] };

describe("multi-select Formik fields", () => {
  test("a touched multi select with an error shows the error variant", () => {
    const { container } = render(
      <Formik
        initialValues={emptyForm}
        initialTouched={{ fruits: true }}
        initialErrors={{ fruits: "Pick at least one" }}
        validate={requireOne}
        onSubmit={() => {}}
      >
        <InputMultiSelectField
          name="fruits"
          placeholder="Pick fruits"
          options={options}
        />
      </Formik>
    );
    expect(container.querySelector('[data-variant="error"]')).not.toBeNull();
  });

  test("a pick writes the value and clears the error", async () => {
    const user = userEvent.setup({ delay: null });
    let latest: string[] = [];
    const { container } = render(
      <Formik
        initialValues={emptyForm}
        initialTouched={{ fruits: true }}
        initialErrors={{ fruits: "Pick at least one" }}
        validate={(values: FruitForm) => {
          latest = values.fruits;
          return requireOne(values);
        }}
        onSubmit={() => {}}
      >
        <InputMultiComboBoxField
          name="fruits"
          placeholder="Pick fruits"
          options={options}
        />
      </Formik>
    );
    await user.click(screen.getByPlaceholderText("Pick fruits"));
    await user.click(screen.getByRole("option", { name: /Apple/ }));
    // Formik validates asynchronously after setValue.
    await waitFor(() => expect(latest).toEqual(["apple"]));
    expect(container.querySelector('[data-variant="error"]')).toBeNull();
  });
});
