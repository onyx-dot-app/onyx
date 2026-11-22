import { fireEvent, render, screen, waitFor } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import { FilePickerButton } from "@opal/components";

describe("FilePickerButton", () => {
  it("hands picked files to onFiles", async () => {
    const onFiles = jest.fn();
    render(
      <FilePickerButton inputLabel="Add files" onFiles={onFiles}>
        Add File
      </FilePickerButton>
    );
    const file = new File(["a"], "a.txt", { type: "text/plain" });
    await userEvent.upload(screen.getByLabelText("Add files"), file);
    await waitFor(() => expect(onFiles).toHaveBeenCalledWith([file]));
  });

  it("hands files dropped on the button to onFiles", async () => {
    const onFiles = jest.fn();
    render(
      <FilePickerButton inputLabel="Add files" onFiles={onFiles}>
        Add File
      </FilePickerButton>
    );
    const file = new File(["b"], "b.txt", { type: "text/plain" });
    fireEvent.drop(screen.getByRole("button", { name: "Add File" }), {
      dataTransfer: {
        files: [file],
        items: [{ kind: "file", type: file.type, getAsFile: () => file }],
        types: ["Files"],
      },
    });
    await waitFor(() => expect(onFiles).toHaveBeenCalled());
    expect(onFiles.mock.calls[0]?.[0]?.[0]?.name).toBe("b.txt");
  });
});
