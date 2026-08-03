import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";
import { Modal } from "react-native";

import { FilePickerSheet } from "@/components/chat/FilePickerSheet";
import { makeProjectFile } from "@/chat/__tests__/fixtures";
import { UserFileStatus, type ProjectFile } from "@/chat/contracts/projects";

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

function recent(id: string, name: string): ProjectFile {
  return makeProjectFile({ id, name, file_id: id });
}

// Chosen action fires only after the modal reports dismissal (iOS presentation-conflict guard).
function fireDismiss() {
  fireEvent(screen.UNSAFE_getByType(Modal), "dismiss");
}

function renderSheet(
  overrides: Partial<Parameters<typeof FilePickerSheet>[0]> = {},
) {
  const props = {
    visible: true,
    onClose: jest.fn(),
    onUploadDocuments: jest.fn(),
    onUploadPhotos: jest.fn(),
    recentFiles: [] as ProjectFile[],
    onPickRecent: jest.fn(),
    isLoadingRecent: false,
    ...overrides,
  };
  render(<FilePickerSheet {...props} />);
  return props;
}

describe("FilePickerSheet", () => {
  it("offers the two device-upload actions (after the sheet dismisses)", () => {
    const props = renderSheet();

    fireEvent.press(screen.getByText("Upload from device"));
    fireDismiss();
    expect(props.onUploadDocuments).toHaveBeenCalledTimes(1);

    fireEvent.press(screen.getByText("Choose photos"));
    fireDismiss();
    expect(props.onUploadPhotos).toHaveBeenCalledTimes(1);
  });

  it("lists recent files and links the tapped one", () => {
    const props = renderSheet({
      recentFiles: [recent("f1", "notes.txt"), recent("f2", "chart.png")],
    });

    expect(screen.getByText("notes.txt")).toBeTruthy();
    fireEvent.press(screen.getByText("chart.png"));
    fireDismiss();
    expect(props.onPickRecent).toHaveBeenCalledWith("f2");
  });

  it("shows an empty state when there are no recent files", () => {
    renderSheet({ recentFiles: [] });
    expect(screen.getByText("No recent files to add.")).toBeTruthy();
  });

  it("shows in-flight files with a status hint; an uploading one is not tappable", () => {
    const props = renderSheet({
      recentFiles: [
        makeProjectFile({
          id: "up",
          name: "uploading.pdf",
          file_id: "up",
          status: UserFileStatus.UPLOADING,
        }),
        makeProjectFile({
          id: "idx",
          name: "indexing.pdf",
          file_id: "idx",
          status: UserFileStatus.INDEXING,
        }),
      ],
    });

    expect(screen.getByText("Uploading…")).toBeTruthy();
    expect(screen.getByText("Indexing…")).toBeTruthy();

    // No server id yet → disabled, nothing to defer.
    fireEvent.press(screen.getByText("uploading.pdf"));
    expect(props.onPickRecent).not.toHaveBeenCalled();

    // Indexing (has a server id) → pickable.
    fireEvent.press(screen.getByText("indexing.pdf"));
    fireDismiss();
    expect(props.onPickRecent).toHaveBeenCalledWith("idx");
  });
});
