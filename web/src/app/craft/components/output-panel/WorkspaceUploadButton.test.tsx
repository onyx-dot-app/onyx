import {
  act,
  deferred,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@tests/setup/test-utils";
import { toast } from "@opal/layouts";
import { WorkspaceUploadButton } from "@/app/craft/components/output-panel/WorkspaceUploadButton";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import {
  uploadFile,
  type UploadFileResponse,
} from "@/app/craft/services/apiServices";

jest.mock("@/app/craft/services/apiServices", () => ({
  ...jest.requireActual("@/app/craft/services/apiServices"),
  uploadFile: jest.fn(),
}));

beforeEach(() => {
  jest.mocked(uploadFile).mockReset();
  useBuildSessionStore.setState({
    currentSessionId: null,
    sessions: new Map(),
  });
  useBuildSessionStore.getState().createSession("session");
});

afterEach(() => jest.restoreAllMocks());

function picker() {
  return screen.getByLabelText("Upload files", { selector: "input" });
}

it("opens a hidden picker and refreshes workspace files after upload", async () => {
  jest.mocked(uploadFile).mockResolvedValue({
    filename: "notes.txt",
    path: "notes.txt",
    size_bytes: 5,
  });
  render(<WorkspaceUploadButton sessionId="session" />);
  const input = picker();
  const openPicker = jest.spyOn(input, "click");
  fireEvent.click(screen.getByRole("button", { name: "Upload files" }));
  expect(openPicker).toHaveBeenCalledTimes(1);
  expect(input).not.toBeVisible();
  const file = new File(["hello"], "notes.txt", { type: "text/plain" });
  fireEvent.change(input, { target: { files: [file] } });
  await waitFor(() => expect(uploadFile).toHaveBeenCalledWith("session", file));
  await waitFor(() =>
    expect(
      useBuildSessionStore.getState().sessions.get("session")?.filesNeedsRefresh
    ).toBe(1)
  );
});

it("disables the picker and shows pending state until upload finishes", async () => {
  const request = deferred<UploadFileResponse>();
  jest.mocked(uploadFile).mockReturnValue(request.promise);
  render(<WorkspaceUploadButton sessionId="session" />);
  const button = screen.getByRole("button", { name: "Upload files" });
  fireEvent.change(picker(), {
    target: { files: [new File(["hello"], "notes.txt")] },
  });
  expect(button).toBeDisabled();
  expect(button).toHaveAttribute("aria-busy", "true");
  expect(picker()).toBeDisabled();
  await act(async () =>
    request.resolve({ filename: "notes.txt", path: "notes.txt", size_bytes: 5 })
  );
  expect(button).not.toBeDisabled();
  expect(button).toHaveAttribute("aria-busy", "false");
});

it("refreshes completed files and reports a later batch failure", async () => {
  const error = jest.spyOn(toast, "error").mockReturnValue("upload-error");
  jest
    .mocked(uploadFile)
    .mockResolvedValueOnce({
      filename: "saved.txt",
      path: "saved.txt",
      size_bytes: 5,
    })
    .mockRejectedValueOnce(new Error("Upload failed"));
  render(<WorkspaceUploadButton sessionId="session" />);
  fireEvent.change(picker(), {
    target: {
      files: [
        new File(["saved"], "saved.txt"),
        new File(["failed"], "failed.txt"),
      ],
    },
  });
  await waitFor(() =>
    expect(error).toHaveBeenCalledWith("Could not upload files. Try again.")
  );
  expect(uploadFile).toHaveBeenCalledTimes(2);
  expect(
    useBuildSessionStore.getState().sessions.get("session")?.filesNeedsRefresh
  ).toBe(1);
});

it("does not upload when the workspace action is disabled", () => {
  render(<WorkspaceUploadButton sessionId="session" disabled />);
  expect(screen.getByRole("button", { name: "Upload files" })).toBeDisabled();
  expect(picker()).toBeDisabled();
  fireEvent.change(picker(), {
    target: { files: [new File(["hello"], "notes.txt")] },
  });
  expect(uploadFile).not.toHaveBeenCalled();
});
