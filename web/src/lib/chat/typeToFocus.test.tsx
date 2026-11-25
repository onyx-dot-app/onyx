import { fireEvent, render, screen } from "@tests/setup/test-utils";
import {
  type TypeToFocusTarget,
  typeToFocusHandlers,
} from "@/lib/chat/typeToFocus";

function renderPage() {
  const composer: TypeToFocusTarget = { focus: jest.fn(), paste: jest.fn() };
  const ref = { current: composer };
  render(
    <>
      <div data-testid="page" tabIndex={-1} {...typeToFocusHandlers(ref)}>
        <button type="button">Copy</button>
        <input aria-label="field" />
      </div>
      <div data-testid="outside" tabIndex={-1} />
    </>
  );
  return { composer, page: screen.getByTestId("page") };
}

describe("typeToFocusHandlers", () => {
  it("sends a printable key typed on the page to the composer", () => {
    const { composer, page } = renderPage();
    fireEvent.keyDown(page, { key: "a" });
    expect(composer.focus).toHaveBeenCalledTimes(1);
  });

  it("leaves shortcuts and named keys alone", () => {
    const { composer, page } = renderPage();
    fireEvent.keyDown(page, { key: "k", metaKey: true });
    fireEvent.keyDown(page, { key: "1", altKey: true });
    fireEvent.keyDown(page, { key: "Enter" });
    fireEvent.keyDown(page, { key: "Escape" });
    expect(composer.focus).not.toHaveBeenCalled();
  });

  it("leaves keys typed in a field alone", () => {
    const { composer } = renderPage();
    fireEvent.keyDown(screen.getByLabelText("field"), { key: "a" });
    expect(composer.focus).not.toHaveBeenCalled();
  });

  it("leaves Space on a button alone", () => {
    const { composer } = renderPage();
    const button = screen.getByRole("button", { name: "Copy" });
    fireEvent.keyDown(button, { key: " " });
    expect(composer.focus).not.toHaveBeenCalled();
    fireEvent.keyDown(button, { key: "a" });
    expect(composer.focus).toHaveBeenCalledTimes(1);
  });

  it("leaves keys alone while a dialog or menu is open", () => {
    const { composer, page } = renderPage();
    const menu = document.createElement("div");
    menu.setAttribute("role", "menu");
    document.body.append(menu);
    fireEvent.keyDown(page, { key: "a" });
    expect(composer.focus).not.toHaveBeenCalled();
    menu.remove();
  });

  it("ignores keys typed outside the page", () => {
    const { composer } = renderPage();
    fireEvent.keyDown(screen.getByTestId("outside"), { key: "a" });
    fireEvent.keyDown(document.body, { key: "a" });
    expect(composer.focus).not.toHaveBeenCalled();
  });

  it("sends a paste on the page to the composer, but not one in a field", () => {
    const { composer, page } = renderPage();
    const clipboardData = { getData: () => "hello" };

    fireEvent.paste(screen.getByLabelText("field"), { clipboardData });
    expect(composer.paste).not.toHaveBeenCalled();

    const notCancelled = fireEvent.paste(page, { clipboardData });
    expect(notCancelled).toBe(false);
    expect(composer.paste).toHaveBeenCalledWith(clipboardData);
  });
});
