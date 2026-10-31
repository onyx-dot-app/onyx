import React from "react";
import { act, fireEvent, screen, within } from "@testing-library/react";
import { deferred, render } from "@tests/setup/test-utils";
import { draftKey } from "@/hooks/useDraft";
import type { BaseInputBarHandle } from "@/sections/input/BaseInputBar";
import CraftInputBar from "@/app/craft/components/CraftInputBar";
import {
  UploadFileStatus,
  type BuildFile,
} from "@/app/craft/contexts/UploadFilesContext";

let mockUserId: string | null = "user";
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: mockUserId ? { id: mockUserId } : null }),
}));

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

let mockDeleteBeforeToken: (token: string) => boolean | undefined;
jest.mock("@/hooks/useSlashPicker", () => ({
  __esModule: true,
  default: ({
    inputRef,
  }: {
    inputRef: React.RefObject<BaseInputBarHandle | null>;
  }) => {
    mockDeleteBeforeToken = (token) =>
      inputRef.current?.deleteBeforeToken(token);
    return {
      open: false,
      anchorRect: null,
      query: "",
      onInput: jest.fn(),
      onSelectionChange: jest.fn(),
      onSelect: jest.fn(),
      onClose: jest.fn(),
      reset: jest.fn(),
    };
  },
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

beforeEach(() => {
  mockUserId = "user";
  sessionStorage.clear();
});

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

  it("does not restore submitted text", async () => {
    const onSubmit = jest.fn();
    const { unmount } = render(
      <CraftInputBar onSubmit={onSubmit} isRunning={false} />
    );
    fireEvent.keyDown(enterText("Send this"), { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledWith("Send this", attachedFiles);
    unmount();
    await act(async () => {});
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

describe("Craft draft review regressions", () => {
  it.each([true, false])(
    "handles async acceptance after unmount: %s",
    async (accepted) => {
      const pending = deferred<boolean>();
      const onSubmit = jest.fn(() => pending.promise);
      const { unmount } = render(
        <CraftInputBar onSubmit={onSubmit} isRunning={false} />
      );
      const input = enterText("Pending draft");
      fireEvent.keyDown(input, { key: "Enter" });
      fireEvent.keyDown(input, { key: "Enter" });
      expect(onSubmit).toHaveBeenCalledTimes(1);
      expect(input).toHaveAttribute("contenteditable", "false");
      expect(sessionStorage.getItem(draftKey("craft", "user:new"))).toBe(
        JSON.stringify("Pending draft")
      );
      unmount();
      await act(async () => pending.resolve(accepted));
      render(<CraftInputBar onSubmit={onSubmit} isRunning={false} />);
      expect(screen.getByRole("textbox").textContent).toBe(
        accepted ? "" : "Pending draft"
      );
    }
  );

  it("preserves text and attachments after a rejected submission", async () => {
    mockClearFiles.mockClear();
    const onSubmit = jest.fn().mockResolvedValue(false);
    render(<CraftInputBar onSubmit={onSubmit} isRunning={false} />);
    await act(async () =>
      fireEvent.keyDown(enterText("Keep me"), { key: "Enter" })
    );
    expect(screen.getByRole("textbox")).toHaveTextContent("Keep me");
    expect(screen.getByRole("textbox")).toHaveAttribute(
      "contenteditable",
      "true"
    );
    expect(mockClearFiles).not.toHaveBeenCalled();
  });

  it("restores edited paste-tile text after navigation without dismissing the popover", () => {
    const props = { onSubmit: jest.fn(), isRunning: false };
    const { unmount } = render(<CraftInputBar {...props} />);
    const input = screen.getByRole("textbox");
    fireEvent.paste(input, {
      clipboardData: {
        getData: () => "Original text ".repeat(30),
        items: [],
        files: [],
      },
    });
    const tile = input.querySelector<HTMLElement>("[data-rich-tile]");
    if (!tile) throw new Error("Expected a paste tile");
    fireEvent.click(tile);
    fireEvent.change(within(screen.getByRole("dialog")).getByRole("textbox"), {
      target: { value: "Corrected text" },
    });
    unmount();
    render(<CraftInputBar {...props} />);
    expect(screen.getByRole("textbox").textContent).toBe("Corrected text");
  });

  it("does not restore a slash query removed by the picker", () => {
    const props = { onSubmit: jest.fn(), isRunning: false };
    const { unmount } = render(<CraftInputBar {...props} />);
    const input = enterText("Prompt /pptx");
    const range = document.createRange();
    range.selectNodeContents(input);
    range.collapse(false);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    // The picker removes a token immediately before a text-node caret.
    const textNode = input.firstChild;
    if (!textNode) throw new Error("Expected input text");
    range.setStart(textNode, textNode.textContent?.length ?? 0);
    range.collapse(true);
    selection?.addRange(range);
    act(() => {
      expect(mockDeleteBeforeToken("/pptx")).toBe(true);
    });
    unmount();
    render(<CraftInputBar {...props} />);
    expect(screen.getByRole("textbox").textContent).toBe("Prompt ");
  });
});

it("clears only the submitted draft when another session mounts during handoff", async () => {
  const pending = deferred<boolean>();
  const { unmount } = render(
    <CraftInputBar onSubmit={() => pending.promise} isRunning={false} />
  );
  fireEvent.keyDown(enterText("Welcome submission"), { key: "Enter" });
  unmount();
  render(
    <CraftInputBar sessionId="other" onSubmit={jest.fn()} isRunning={false} />
  );
  enterText("Other session draft");
  await act(async () => pending.resolve(true));
  expect(sessionStorage.getItem(draftKey("craft", "user:new"))).toBeNull();
  expect(sessionStorage.getItem(draftKey("craft", "user:other"))).toBe(
    JSON.stringify("Other session draft")
  );
  expect(screen.getByRole("textbox")).toHaveTextContent("Other session draft");
});

it("isolates account drafts and ignores legacy drafts without an owner", () => {
  sessionStorage.setItem(
    draftKey("craft", "new"),
    JSON.stringify("Legacy private draft")
  );
  const props = { onSubmit: jest.fn(), isRunning: false };
  const { rerender } = render(<CraftInputBar {...props} />);
  expect(screen.getByRole("textbox")).toBeEmptyDOMElement();
  enterText("First account draft");
  mockUserId = null;
  rerender(<CraftInputBar {...props} onSubmit={jest.fn()} />);
  expect(screen.getByRole("textbox")).toBeEmptyDOMElement();
  mockUserId = "user";
  rerender(<CraftInputBar {...props} onSubmit={jest.fn()} />);
  expect(screen.getByRole("textbox")).toHaveTextContent("First account draft");
  mockUserId = "second-user";
  rerender(<CraftInputBar {...props} onSubmit={jest.fn()} />);
  expect(screen.getByRole("textbox")).toBeEmptyDOMElement();
  enterText("Second account draft");
  mockUserId = "user";
  rerender(<CraftInputBar {...props} onSubmit={jest.fn()} />);
  expect(screen.getByRole("textbox")).toHaveTextContent("First account draft");
  mockUserId = "second-user";
  rerender(<CraftInputBar {...props} onSubmit={jest.fn()} />);
  expect(screen.getByRole("textbox")).toHaveTextContent("Second account draft");
});

it("does not persist text without a signed-in owner", () => {
  mockUserId = null;
  render(<CraftInputBar onSubmit={jest.fn()} isRunning={false} />);
  enterText("No owner");
  expect(sessionStorage.length).toBe(0);
});
