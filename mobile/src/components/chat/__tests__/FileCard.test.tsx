import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { FileCard } from "@/components/chat/FileCard";
import { makeProjectFile } from "@/chat/__tests__/fixtures";
import { UserFileStatus, type ProjectFile } from "@/chat/contracts/projects";
import { ChatFileType } from "@/chat/interfaces";
import { useUserFileStore } from "@/state/userFileStore";

// The bearer image pulls the config→storage(MMKV) chain; stub it (the image card's own
// View carries the testID we assert on). `() => null` avoids JSX in the factory.
jest.mock("@/components/chat/AttachmentImage", () => ({
  AttachmentImage: () => null,
}));

function makeFile(overrides: Partial<ProjectFile> = {}): ProjectFile {
  return makeProjectFile({ name: "doc.pdf", ...overrides });
}

describe("FileCard", () => {
  beforeEach(() => {
    useUserFileStore.setState({ progressById: {} });
  });

  it("shows a document as a pill with its extension label + a remove control", () => {
    const onRemove = jest.fn();
    render(<FileCard file={makeFile({ id: "u1" })} onRemove={onRemove} />);

    expect(screen.getByTestId("file-doc-card")).toBeTruthy();
    expect(screen.getByText("PDF")).toBeTruthy();
    fireEvent.press(screen.getByLabelText("Remove doc.pdf"));
    expect(onRemove).toHaveBeenCalledWith("u1");
  });

  it("stays removable while indexing (so the user can unblock send)", () => {
    render(
      <FileCard
        file={makeFile({ status: UserFileStatus.INDEXING })}
        onRemove={jest.fn()}
      />,
    );

    expect(screen.getByText("Indexing…")).toBeTruthy();
    expect(screen.getByLabelText("Remove doc.pdf")).toBeTruthy();
  });

  it("renders upload progress (from the store) and blocks removal while UPLOADING", () => {
    useUserFileStore.setState({ progressById: { up1: 0.42 } });
    render(
      <FileCard
        file={makeFile({ id: "up1", status: UserFileStatus.UPLOADING })}
        onRemove={jest.fn()}
      />,
    );

    expect(screen.getByText("Uploading… 42%")).toBeTruthy();
    expect(screen.queryByLabelText("Remove doc.pdf")).toBeNull();
  });

  it("renders an image as a thumbnail card, not a doc pill", () => {
    const onRemove = jest.fn();
    render(
      <FileCard
        file={makeFile({
          id: "img1",
          name: "pic.png",
          chat_file_type: ChatFileType.IMAGE,
          status: UserFileStatus.COMPLETED,
        })}
        onRemove={onRemove}
      />,
    );

    expect(screen.getByTestId("file-image-card")).toBeTruthy();
    expect(screen.queryByTestId("file-doc-card")).toBeNull();
    fireEvent.press(screen.getByLabelText("Remove pic.png"));
    expect(onRemove).toHaveBeenCalledWith("img1");
  });

  it("renders a failed image as a pill (not a thumbnail), still removable", () => {
    render(
      <FileCard
        file={makeFile({
          name: "broken.png",
          chat_file_type: ChatFileType.IMAGE,
          status: UserFileStatus.FAILED,
        })}
        onRemove={jest.fn()}
      />,
    );

    expect(screen.queryByTestId("file-image-card")).toBeNull();
    expect(screen.getByTestId("file-doc-card")).toBeTruthy();
    expect(screen.getByText("Failed")).toBeTruthy();
    expect(screen.getByLabelText("Remove broken.png")).toBeTruthy();
  });

  it("is read-only (no remove control) when onRemove is omitted", () => {
    render(<FileCard file={makeFile({ status: UserFileStatus.COMPLETED })} />);
    expect(screen.queryByLabelText("Remove doc.pdf")).toBeNull();
  });
});
