import { render, screen } from "@tests/setup/test-utils";
import { ReadOnlyRegion } from "@opal/components";

function Content() {
  return (
    <div>
      <button type="button">Save</button>
      <div role="button" tabIndex={0} data-testid="card">
        A card with a key handler
      </div>
    </div>
  );
}

test("a read-only region disables form controls and is inert", () => {
  render(
    <ReadOnlyRegion tooltip="Available on the Enterprise plan">
      <Content />
    </ReadOnlyRegion>
  );

  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  // The disabled fieldset does not reach a focusable div; inert does.
  expect(screen.getByTestId("card").closest("[inert]")).not.toBeNull();
  expect(
    screen.getByText("Available on the Enterprise plan")
  ).toBeInTheDocument();
});

test("readOnly false renders the children as they are", () => {
  render(
    <ReadOnlyRegion readOnly={false}>
      <Content />
    </ReadOnlyRegion>
  );

  expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  expect(screen.getByTestId("card").closest("[inert]")).toBeNull();
});
