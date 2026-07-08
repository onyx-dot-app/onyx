import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { FileCard } from "@/components/chat/FileCard";
import { makeProjectFile } from "@/chat/__tests__/fixtures";
import { UserFileStatus, type ProjectFile } from "@/chat/contracts/projects";

function makeFile(overrides: Partial<ProjectFile> = {}): ProjectFile {
  return makeProjectFile({ name: "doc.pdf", ...overrides });
}

describe("FileCard", () => {
  it("shows the extension label and a remove button once settled", () => {
    const onRemove = jest.fn();
    render(<FileCard file={makeFile({})} onRemove={onRemove} />);

    expect(screen.getByText("PDF")).toBeTruthy();
    fireEvent.press(screen.getByLabelText("Remove doc.pdf"));
    expect(onRemove).toHaveBeenCalledTimes(1);
  });

  it("treats INDEXING as still-processing (no remove, Indexing… label)", () => {
    render(
      <FileCard
        file={makeFile({ status: UserFileStatus.INDEXING })}
        onRemove={jest.fn()}
      />,
    );

    expect(screen.getByText("Indexing…")).toBeTruthy();
    expect(screen.queryByLabelText("Remove doc.pdf")).toBeNull();
  });

  it("renders upload progress while UPLOADING", () => {
    render(
      <FileCard
        file={makeFile({ status: UserFileStatus.UPLOADING })}
        progress={0.42}
      />,
    );

    expect(screen.getByText("Uploading… 42%")).toBeTruthy();
  });
});
