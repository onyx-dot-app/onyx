import { render, screen } from "@tests/setup/test-utils";
import ButtonRenaming from "@/refresh-components/buttons/ButtonRenaming";

test("the rename field uses the row title's font and shows an outline", () => {
  render(
    <ButtonRenaming
      initialName="Quarterly plan"
      onRename={jest.fn()}
      onClose={jest.fn()}
    />
  );
  const field = screen.getByRole("textbox");
  expect(field).toHaveClass(
    "font-main-ui-body",
    "outline",
    "outline-border-04"
  );
  expect(field).not.toHaveClass("font-main-content-body");
});
