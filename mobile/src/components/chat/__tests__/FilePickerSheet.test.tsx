import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { FilePickerSheet } from "@/components/chat/FilePickerSheet";
import { makeProjectFile } from "@/chat/__tests__/fixtures";
import type { ProjectFile } from "@/chat/contracts/projects";

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

function recent(id: string, name: string): ProjectFile {
  return makeProjectFile({ id, name, file_id: id });
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
  it("offers the two device-upload actions", () => {
    const props = renderSheet();

    fireEvent.press(screen.getByText("Upload from device"));
    expect(props.onUploadDocuments).toHaveBeenCalledTimes(1);

    fireEvent.press(screen.getByText("Choose photos"));
    expect(props.onUploadPhotos).toHaveBeenCalledTimes(1);
  });

  it("lists recent files and links the tapped one", () => {
    const props = renderSheet({
      recentFiles: [recent("f1", "notes.txt"), recent("f2", "chart.png")],
    });

    expect(screen.getByText("notes.txt")).toBeTruthy();
    fireEvent.press(screen.getByText("chart.png"));
    expect(props.onPickRecent).toHaveBeenCalledWith("f2");
  });

  it("shows an empty state when there are no recent files", () => {
    renderSheet({ recentFiles: [] });
    expect(screen.getByText("No recent files to add.")).toBeTruthy();
  });
});
