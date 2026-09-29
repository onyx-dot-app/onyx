import { act, render } from "@testing-library/react";
import { AgentChatInput } from "@/lib/agents/components/AgentViewerModal";
import { ChatFileType } from "@/app/app/interfaces";
import type { FullAgent } from "@/lib/agents/types";
import type { CategorizedFiles, ProjectFile } from "@/lib/projects/types";
import { UserFileStatus } from "@/lib/projects/types";

type InputBarProps = {
  handleFileUpload: (files: File[]) => Promise<void>;
  onSubmit: (message: string) => void;
};

type StateUpdater =
  | ProjectFile[]
  | ((previous: ProjectFile[]) => ProjectFile[]);

let mockInputBarProps: InputBarProps | undefined;
let mockBeginUpload = jest.fn();
let mockSetCurrentMessageFiles = jest.fn();
let mockHandOffToNewChatWith = jest.fn();
let mockToastError = jest.fn();
let currentFiles: ProjectFile[] = [];

jest.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
}));

jest.mock("@/sections/input/AppInputBar", () => ({
  __esModule: true,
  default: (props: InputBarProps) => {
    mockInputBarProps = props;
    return null;
  },
}));

jest.mock("@/lib/projects/providers", () => ({
  useProjectsContext: () => ({
    beginUpload: mockBeginUpload,
    setCurrentMessageFiles: mockSetCurrentMessageFiles,
  }),
}));

jest.mock("@/lib/hooks", () => ({
  useLlmManager: () => ({
    isLoadingProviders: false,
    llmProviders: [],
    currentLlm: null,
  }),
}));

jest.mock("@/lib/tools/hooks", () => ({
  useMcpServers: () => ({ mcpData: null }),
  useToolConfiguration: () => ({
    handOffToNewChatWith: mockHandOffToNewChatWith,
  }),
}));

jest.mock("@/lib/languageModels/hooks", () => ({
  useLLMProviders: () => ({ llmProviders: [] }),
}));

jest.mock("@/lib/languageModels/utils", () => ({
  getDisplayName: () => null,
  getFinalLLM: () => [null, {}],
  modelSupportsImageInput: () => true,
}));

jest.mock("@opal/layouts", () => ({
  toast: {
    error: (...args: unknown[]) => mockToastError(...args),
  },
}));

function makeProjectFile(
  id: string,
  tempId: string | null,
  status: UserFileStatus
): ProjectFile {
  const timestamp = "2026-09-23T00:00:00.000Z";
  return {
    id,
    name: `${id}.txt`,
    project_id: null,
    user_id: null,
    file_id: id,
    created_at: timestamp,
    status,
    file_type: "text/plain",
    last_accessed_at: timestamp,
    chat_file_type: ChatFileType.DOCUMENT,
    token_count: null,
    chunk_count: null,
    temp_id: tempId,
  };
}

function getInputBarProps(): InputBarProps {
  if (!mockInputBarProps) {
    throw new Error("Agent input bar did not render");
  }
  return mockInputBarProps;
}

async function uploadFile(): Promise<void> {
  const file = new File(["content"], "notes.txt", { type: "text/plain" });
  await act(async () => {
    await getInputBarProps().handleFileUpload([file]);
  });
}

function replaceWithServerFile(serverFile: ProjectFile): void {
  act(() => {
    mockSetCurrentMessageFiles((previous: ProjectFile[]) =>
      previous.map((file: ProjectFile) => ({ ...file, ...serverFile }))
    );
  });
}

describe("AgentChatInput staged uploads", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockInputBarProps = undefined;
    currentFiles = [];
    mockSetCurrentMessageFiles.mockImplementation((update: StateUpdater) => {
      currentFiles =
        typeof update === "function" ? update(currentFiles) : update;
    });
  });

  it("removes an optimistic upload when the viewer closes before completion", async () => {
    const optimistic = makeProjectFile(
      "temp-1",
      "temp-1",
      UserFileStatus.UPLOADING
    );
    mockBeginUpload.mockResolvedValue([optimistic]);
    const onSubmit = jest.fn();
    const view = render(
      <AgentChatInput agent={{ id: 1 } as FullAgent} onSubmit={onSubmit} />
    );

    await uploadFile();
    expect(currentFiles).toEqual([optimistic]);

    view.unmount();
    expect(currentFiles).toEqual([]);
  });

  it("removes the server file after optimistic ID replacement", async () => {
    const optimistic = makeProjectFile(
      "temp-2",
      "temp-2",
      UserFileStatus.UPLOADING
    );
    const serverFile = makeProjectFile(
      "server-2",
      "temp-2",
      UserFileStatus.COMPLETED
    );
    mockBeginUpload.mockResolvedValue([optimistic]);
    const view = render(
      <AgentChatInput agent={{ id: 1 } as FullAgent} onSubmit={jest.fn()} />
    );

    await uploadFile();
    replaceWithServerFile(serverFile);
    const onSuccess = mockBeginUpload.mock.calls[0][2] as (
      result: CategorizedFiles
    ) => void;
    act(() => {
      onSuccess({ user_files: [serverFile], rejected_files: [] });
    });
    expect(currentFiles).toEqual([serverFile]);

    view.unmount();
    expect(currentFiles).toEqual([]);
  });

  it("removes a rejected upload and keeps later closes leak-free", async () => {
    const optimistic = makeProjectFile(
      "temp-3",
      "temp-3",
      UserFileStatus.UPLOADING
    );
    mockBeginUpload.mockResolvedValue([optimistic]);
    const view = render(
      <AgentChatInput agent={{ id: 1 } as FullAgent} onSubmit={jest.fn()} />
    );

    await uploadFile();
    const onFailure = mockBeginUpload.mock.calls[0][3] as (
      failedTempIds: string[]
    ) => void;
    act(() => {
      onFailure(["temp-3"]);
    });
    expect(currentFiles).toEqual([]);

    view.unmount();
    expect(currentFiles).toEqual([]);
  });

  it("preserves a server-replaced upload when submit hands off to chat", async () => {
    const optimistic = makeProjectFile(
      "temp-4",
      "temp-4",
      UserFileStatus.UPLOADING
    );
    const serverFile = makeProjectFile(
      "server-4",
      "temp-4",
      UserFileStatus.COMPLETED
    );
    mockBeginUpload.mockResolvedValue([optimistic]);
    const onSubmit = jest.fn();
    const view = render(
      <AgentChatInput agent={{ id: 1 } as FullAgent} onSubmit={onSubmit} />
    );

    await uploadFile();
    replaceWithServerFile(serverFile);
    const onSuccess = mockBeginUpload.mock.calls[0][2] as (
      result: CategorizedFiles
    ) => void;
    act(() => {
      onSuccess({ user_files: [serverFile], rejected_files: [] });
    });
    act(() => {
      getInputBarProps().onSubmit("continue");
    });
    view.unmount();

    expect(mockHandOffToNewChatWith).toHaveBeenCalledWith(1);
    expect(onSubmit).toHaveBeenCalledWith("continue");
    expect(currentFiles).toEqual([serverFile]);
  });
});
