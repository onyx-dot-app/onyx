import React from "react";
import { fireEvent, screen } from "@testing-library/react";
import { render } from "@tests/setup/test-utils";
import CraftInputBar from "@/app/craft/components/CraftInputBar";
import {
  UploadFileStatus,
  type BuildFile,
} from "@/app/craft/contexts/UploadFilesContext";

const mockClearFiles = jest.fn();
const attachedFiles: BuildFile[] = [
  {
    id: "file-1",
    name: "reference.png",
    status: UploadFileStatus.COMPLETED,
    file_type: "image/png",
    size: 123,
    created_at: "2026-07-28T00:00:00.000Z",
    path: "attachments/reference.png",
  },
];

jest.mock("@/app/craft/contexts/UploadFilesContext", () => {
  const actual = jest.requireActual<
    typeof import("@/app/craft/contexts/UploadFilesContext")
  >("@/app/craft/contexts/UploadFilesContext");
  return {
    ...actual,
    useUploadFilesContext: () => ({
      currentMessageFiles: attachedFiles,
      uploadFiles: jest.fn(),
      removeFile: jest.fn(),
      clearFiles: mockClearFiles,
      hasUploadingFiles: false,
    }),
  };
});

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
}));

jest.mock("swr", () => ({
  __esModule: true,
  default: () => ({ data: [], mutate: jest.fn() }),
  // The test-utils render wrapper mounts the real SWRConfig provider.
  SWRConfig: jest.requireActual("swr").SWRConfig,
}));

jest.mock("@/hooks/useUserSkills", () => ({
  __esModule: true,
  default: () => ({ data: undefined }),
}));

jest.mock("@/hooks/useUserExternalApps", () => ({
  __esModule: true,
  default: () => ({ data: undefined }),
}));

jest.mock("@/lib/mcp/hooks", () => ({
  useCraftMcpServers: () => ({ data: undefined }),
}));

jest.mock("@/hooks/useEscapeInterrupt", () => ({
  useEscapeInterrupt: jest.fn(),
}));

jest.mock("@/hooks/useSlashPicker", () => ({
  __esModule: true,
  default: () => ({
    open: false,
    anchorRect: null,
    query: "",
    onInput: jest.fn(),
    onSelectionChange: jest.fn(),
    onSelect: jest.fn(),
    onClose: jest.fn(),
    reset: jest.fn(),
  }),
}));

jest.mock("@/lib/skills/picker", () => ({
  pickerEntryConnectionPath: () => null,
  pickerEntryKey: () => "",
  pickerEntryPromptPrefix: () => "",
  toPickerSections: () => ({ skills: [], apps: [], mcpServers: [] }),
}));

jest.mock("@/app/craft/components/buildEntryMenuItems", () => ({
  buildEntryMenuItems: () => [],
}));

jest.mock("@/sections/input/EntryInfoPopover", () => () => null);
jest.mock("@/sections/input/EntryPickerPopover", () => () => null);
jest.mock("@/app/craft/components/InterruptHint", () => () => null);
jest.mock("@/app/craft/components/ContextRing", () => () => null);
jest.mock("@/sections/input/InputChipStrip", () => ({
  InputChipStrip: () => null,
}));
jest.mock("@/sections/input/PlusMenuButton", () => ({
  PlusMenuButton: () => null,
}));
jest.mock("@/app/craft/components/UserLibraryModal", () => () => null);

function enterText(text: string) {
  const input = screen.getByRole("textbox", { name: "Message input" });
  input.textContent = text;
  fireEvent.input(input);
  return input;
}

beforeEach(() => sessionStorage.clear());

describe("CraftInputBar queued attachments", () => {
  beforeEach(() => {
    mockClearFiles.mockClear();
  });

  it("transfers composer files to the queued message and clears their association", () => {
    const onQueueMessage = jest.fn();

    render(
      <CraftInputBar
        onSubmit={jest.fn()}
        isRunning
        onQueueMessage={onQueueMessage}
      />
    );

    fireEvent.keyDown(enterText("queued prompt"), { key: "Enter" });

    expect(onQueueMessage).toHaveBeenCalledWith("queued prompt", attachedFiles);
    expect(mockClearFiles).toHaveBeenCalledWith();
  });

  it("keeps composer files when the queue rejects the handoff", () => {
    const onQueueMessage = jest.fn().mockReturnValue(false);
    render(
      <CraftInputBar
        onSubmit={jest.fn()}
        isRunning
        onQueueMessage={onQueueMessage}
      />
    );
    fireEvent.keyDown(enterText("queued prompt"), { key: "Enter" });
    expect(onQueueMessage).toHaveBeenCalledWith("queued prompt", attachedFiles);
    expect(mockClearFiles).not.toHaveBeenCalled();
  });
});

describe("CraftInputBar session drafts", () => {
  it("keeps separate drafts for New Session and existing sessions across navigation", () => {
    const onSubmit = jest.fn();
    const { rerender, unmount } = render(
      <CraftInputBar onSubmit={onSubmit} isRunning={false} />
    );
    enterText("Welcome draft");
    rerender(
      <CraftInputBar sessionId="a" onSubmit={onSubmit} isRunning={false} />
    );
    expect(screen.getByRole("textbox")).toBeEmptyDOMElement();
    enterText("Session A draft");
    rerender(
      <CraftInputBar sessionId="b" onSubmit={onSubmit} isRunning={false} />
    );
    expect(screen.getByRole("textbox")).toBeEmptyDOMElement();
    enterText("Session B draft");
    rerender(
      <CraftInputBar sessionId="a" onSubmit={onSubmit} isRunning={false} />
    );
    expect(screen.getByRole("textbox")).toHaveTextContent("Session A draft");
    rerender(<CraftInputBar onSubmit={onSubmit} isRunning={false} />);
    expect(screen.getByRole("textbox")).toHaveTextContent("Welcome draft");
    enterText("Latest welcome draft");
    unmount();
    render(<CraftInputBar onSubmit={onSubmit} isRunning={false} />);
    expect(screen.getByRole("textbox")).toHaveTextContent(
      "Latest welcome draft"
    );
  });

  it("does not restore submitted text", () => {
    const onSubmit = jest.fn();
    const { unmount } = render(
      <CraftInputBar onSubmit={onSubmit} isRunning={false} />
    );
    fireEvent.keyDown(enterText("Send this"), { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledWith("Send this", attachedFiles);
    unmount();
    render(<CraftInputBar onSubmit={onSubmit} isRunning={false} />);
    expect(screen.getByRole("textbox")).toBeEmptyDOMElement();
  });

  it.each([true, false])(
    "clears queued text only when accepted: %s",
    (accepted) => {
      const props = {
        onSubmit: jest.fn(),
        isRunning: true,
        onQueueMessage: () => accepted,
      };
      const { unmount } = render(<CraftInputBar {...props} />);
      fireEvent.keyDown(enterText("Queue this"), { key: "Enter" });
      unmount();
      render(<CraftInputBar {...props} />);
      expect(screen.getByRole("textbox").textContent).toBe(
        accepted ? "" : "Queue this"
      );
    }
  );
});
