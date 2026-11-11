import { fireEvent, render, screen } from "@tests/setup/test-utils";
import { SvgLoader } from "@opal/icons";
import ProviderModal from "@/sections/modals/ProviderModal";

function renderModal(onSubmit: () => void) {
  render(
    <ProviderModal
      open
      onOpenChange={jest.fn()}
      icon={SvgLoader}
      title="Provider"
      onSubmit={onSubmit}
    >
      <input aria-label="API Key" />
    </ProviderModal>
  );
  return screen.getByLabelText("API Key");
}

describe("ProviderModal Enter to submit", () => {
  it("submits on a plain Enter", () => {
    const onSubmit = jest.fn();
    fireEvent.keyDown(renderModal(onSubmit), { key: "Enter", keyCode: 13 });
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("does not submit on the Enter that confirms an IME candidate", () => {
    const onSubmit = jest.fn();
    const input = renderModal(onSubmit);
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    fireEvent.keyDown(input, { key: "Enter", keyCode: 229 });
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
