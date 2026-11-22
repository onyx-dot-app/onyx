import {
  deferred,
  fireEvent,
  render,
  renderHook,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import { SWRConfig } from "swr";
import { act, createRef } from "react";
import AppInputBar, {
  type AppInputBarHandle,
  type AppInputBarProps,
} from "@/sections/input/AppInputBar";
import { type ProjectFile, UserFileStatus } from "@/lib/projects/types";
import { ChatFileType } from "@/app/app/types";
import { useLlmManager } from "@/lib/hooks";
import { useToolConfiguration } from "@/lib/tools/hooks";
import { useChatSessionQueue } from "@/lib/chat/hooks";
import type { MinimalAgent } from "@/lib/agents/types";
import { Button } from "@opal/components";
import type { ToolSnapshot } from "@/lib/tools/types";
import { SEARCH_TOOL_ID } from "@/lib/tools/constants";
import type { ChatState } from "@/app/app/types";
import type { PickerSections } from "@/lib/skills/picker";
import { useChatSkills } from "@/lib/skills/hooks";
import type { ChatSkill } from "@/lib/skills/types";
import { draftKey } from "@/hooks/useDraft";
import type MicrophoneButton from "@/sections/input/MicrophoneButton";
import {
  MAX_MENTIONS_PER_MESSAGE,
  type ComposedMessage,
} from "@/lib/chat/types";

function memberTool(overrides: Partial<ToolSnapshot> = {}): ToolSnapshot {
  return {
    id: 7,
    name: "Reports API",
    display_name: "Reports API",
    description: "Read weekly reports and project summaries.",
    definition: {},
    custom_headers: [],
    in_code_tool_id: null,
    passthrough_auth: false,
    enabled: true,
    chat_selectable: true,
    agent_creation_selectable: true,
    default_enabled: false,
    permissions: {},
    ...overrides,
  };
}

const storedMcpTool = memberTool({
  id: 71,
  name: "search_issues",
  display_name: "Search issues",
  description: "Find issues in the projects you can access.",
  definition: null,
  mcp_server_id: 7,
});

jest.mock("@/lib/hooks", () => ({
  useLlmManager: () => ({ isLoadingProviders: true }),
}));
let mockUser: { preferences: { shortcut_enabled: boolean } } | null = null;
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: mockUser, isAdmin: false }),
}));
const NO_SKILLS: PickerSections = { skills: [], apps: [], mcpServers: [] };
// Null uses the real hook, which fetches the skills.
let mockChatSkills: PickerSections | null = NO_SKILLS;
jest.mock("@/lib/skills/hooks", () => {
  const actual =
    jest.requireActual<typeof import("@/lib/skills/hooks")>(
      "@/lib/skills/hooks"
    );
  return {
    ...actual,
    useChatSkills: (options: { builtIns: boolean }) =>
      mockChatSkills === null
        ? actual.useChatSkills(options)
        : { entries: mockChatSkills, onInputFocus: () => undefined },
  };
});
let mockIncognitoEnabled = false;
jest.mock("@/providers/IncognitoProvider", () => ({
  useIncognito: () => ({ incognitoEnabled: mockIncognitoEnabled }),
}));
jest.mock("@/providers/QueryControllerProvider", () => ({
  useQueryController: () => ({ state: { phase: "idle", appMode: "chat" } }),
}));
jest.mock("@/providers/VoiceModeProvider", () => ({
  useVoiceMode: () => ({ stopTTS: jest.fn() }),
}));
let mockSttEnabled = false;
jest.mock("@/hooks/useVoiceStatus", () => ({
  useVoiceStatus: () => ({ sttEnabled: mockSttEnabled }),
}));
let mockMicrophone: React.ComponentProps<typeof MicrophoneButton> | null = null;
jest.mock("@/sections/input/MicrophoneButton", () => ({
  __esModule: true,
  default: (props: React.ComponentProps<typeof MicrophoneButton>) => {
    mockMicrophone = props;
    return null;
  },
}));
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ appName: "Onyx" }),
}));
jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
}));
jest.mock("@/lib/navigation/hooks", () => ({
  useAppPosition: () => ({
    isNewSession: () => true,
    chat: () => null,
    agent: () => null,
    project: () => null,
  }),
}));
jest.mock("@/lib/integrations/hooks", () => ({
  ...jest.requireActual<typeof import("@/lib/integrations/hooks")>(
    "@/lib/integrations/hooks"
  ),
  useAgentIntegrationIds: () => ({
    integrationIds: [],
    isLoading: false,
    error: undefined,
  }),
  useAgentChatIntegrations: () => ({
    integrationIds: [],
    integrations: [],
    isLoading: false,
    error: undefined,
    refresh: jest.fn(),
  }),
  useAgentIntegrationPreferences: () => ({
    loaded: true,
    error: undefined,
    disabledIntegrationIds: () => [],
    setIntegrationsDisabled: jest.fn(),
    retry: jest.fn(),
  }),
}));
jest.mock("@/lib/agents/hooks", () => ({ useActiveAgent: () => undefined }));
const mockProjectsContext: {
  currentMessageFiles: ProjectFile[];
  setCurrentMessageFiles: jest.Mock;
} = { currentMessageFiles: [], setCurrentMessageFiles: jest.fn() };
jest.mock("@/lib/projects/providers", () => ({
  useProjectsContext: () => mockProjectsContext,
}));
jest.mock("@/lib/projects/hooks", () => ({
  useProjects: () => ({ isLoading: false }),
  useActiveProject: () => null,
}));
jest.mock("@/lib/connectors/hooks", () => ({
  useAvailableSources: () => ({ isLoading: true }),
}));
jest.mock("@/hooks/usePromptShortcuts", () => ({
  __esModule: true,
  default: () => ({ activePromptShortcuts: [] }),
}));
jest.mock("@/refresh-components/popovers/FilePickerPopover", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/lib/tools/components", () => ({ ToolsPopover: () => null }));

const agent: MinimalAgent = {
  id: 0,
  name: "Default Chat",
  description: "",
  tools: [storedMcpTool],
  starter_messages: null,
  document_sets: [],
  is_public: true,
  is_listed: true,
  display_priority: null,
  is_featured: false,
  builtin_persona: true,
  owner: null,
  owner_group: null,
  user_permission: "VIEWER",
};

function Composer({
  agentId = 0,
  tools = agent.tools,
  inputBarRef,
  chatState = "input",
  disabled = false,
  onSubmit = jest.fn(),
}: {
  agentId?: number;
  tools?: MinimalAgent["tools"];
  inputBarRef?: React.Ref<AppInputBarHandle>;
  chatState?: ChatState;
  disabled?: boolean;
  onSubmit?: AppInputBarProps["onSubmit"];
}) {
  const configuration = useToolConfiguration(agentId);
  const llmManager = useLlmManager();
  const queue = useChatSessionQueue(false);
  return (
    <>
      <Button
        onClick={() =>
          configuration.setToolState(storedMcpTool.id, () => "preferred")
        }
      >
        Prefer selected tool
      </Button>
      <output aria-label="Stored preferred tool">
        {configuration.preferredToolId}
      </output>
      <AppInputBar
        ref={inputBarRef}
        activeAgent={{ ...agent, id: agentId, tools }}
        toolConfiguration={configuration}
        llmManager={llmManager}
        stopGenerating={jest.fn()}
        onSubmit={onSubmit}
        handleFileUpload={jest.fn()}
        deepResearchEnabled={false}
        toggleDeepResearch={jest.fn()}
        chatState={chatState}
        disabled={disabled}
        queue={queue}
      />
    </>
  );
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  mockUser = null;
  mockChatSkills = NO_SKILLS;
  mockIncognitoEnabled = false;
  mockSttEnabled = false;
  mockMicrophone = null;
  mockProjectsContext.currentMessageFiles = [];
  mockProjectsContext.setCurrentMessageFiles.mockClear();
});

test("incognito greys out Deep Research and explains why", async () => {
  mockIncognitoEnabled = true;
  render(
    <Composer
      tools={[memberTool({ id: 1, in_code_tool_id: SEARCH_TOOL_ID })]}
    />
  );
  const button = screen.getByRole("button", { name: "Deep Research" });
  expect(button).toBeDisabled();
  await setupUser().hover(button);
  expect(await screen.findByRole("tooltip")).toHaveTextContent(
    "Deep Research isn't available in incognito mode"
  );
});

describe("restore after a failed send", () => {
  function projectFile(id: string): ProjectFile {
    return {
      id,
      name: `${id}.txt`,
      project_id: null,
      user_id: null,
      file_id: `${id}-file-id`,
      created_at: "2026-01-01T00:00:00Z",
      status: UserFileStatus.COMPLETED,
      file_type: "text/plain",
      last_accessed_at: "2026-01-01T00:00:00Z",
      chat_file_type: ChatFileType.PLAIN_TEXT,
      token_count: null,
      chunk_count: null,
    };
  }
  const failedFiles = [projectFile("failed-file")] satisfies ProjectFile[];

  test("puts the message, its picks and its files back into an empty composer", async () => {
    const inputBarRef = createRef<AppInputBarHandle>();
    const onSubmit = jest.fn();
    render(<Composer inputBarRef={inputBarRef} onSubmit={onSubmit} />);
    act(() =>
      inputBarRef.current?.restore({
        message: "failed @code-review message",
        mentions: [{ type: "skill", name: "code-review" }],
        files: failedFiles,
      })
    );
    const input = screen.getByRole("textbox");
    expect(input).toHaveTextContent("failed @code-review message");
    expect(mockProjectsContext.setCurrentMessageFiles).toHaveBeenCalledWith(
      failedFiles
    );

    await setupUser().type(input, "{Enter}");
    expect(onSubmit).toHaveBeenCalledWith({
      message: "failed @code-review message",
      mentions: [{ type: "skill", name: "code-review", index: 7 }],
    });
  });

  test("keeps text typed while the send was pending", async () => {
    const inputBarRef = createRef<AppInputBarHandle>();
    render(<Composer inputBarRef={inputBarRef} />);
    await setupUser().type(screen.getByRole("textbox"), "newer draft");
    act(() =>
      inputBarRef.current?.restore({
        message: "failed message",
        mentions: [],
        files: failedFiles,
      })
    );
    expect(screen.getByRole("textbox")).toHaveTextContent("newer draft");
    expect(screen.getByRole("textbox")).not.toHaveTextContent("failed message");
    expect(mockProjectsContext.setCurrentMessageFiles).not.toHaveBeenCalled();
  });

  test("keeps files attached while the send was pending", () => {
    mockProjectsContext.currentMessageFiles = [
      projectFile("newer-file"),
    ] satisfies ProjectFile[];
    const inputBarRef = createRef<AppInputBarHandle>();
    render(<Composer inputBarRef={inputBarRef} />);
    act(() =>
      inputBarRef.current?.restore({
        message: "failed message",
        mentions: [],
        files: failedFiles,
      })
    );
    expect(screen.getByRole("textbox")).not.toHaveTextContent("failed message");
    expect(mockProjectsContext.setCurrentMessageFiles).not.toHaveBeenCalled();
  });
});

test.each([
  ["input", false, "true"],
  ["streaming", false, "false"],
  ["cancelling", false, "false"],
  ["input", true, "false"],
] as const)(
  "the composer accepts a normal send only when idle and enabled (%s, disabled=%s)",
  (chatState, disabled, accepts) => {
    const { container } = render(
      <Composer chatState={chatState} disabled={disabled} />
    );
    expect(container.querySelector("#onyx-chat-input")).toHaveAttribute(
      "data-accepts-send",
      accepts
    );
  }
);

describe("`@` skill mentions", () => {
  // jsdom has no layout, so ranges cannot measure the caret.
  const rangeRect = Range.prototype.getBoundingClientRect;
  beforeAll(() => {
    Range.prototype.getBoundingClientRect = () => new DOMRect();
  });
  afterAll(() => {
    Range.prototype.getBoundingClientRect = rangeRect;
  });

  beforeEach(() => {
    mockUser = { preferences: { shortcut_enabled: true } };
    mockChatSkills = {
      ...NO_SKILLS,
      skills: [
        {
          kind: "skill",
          slug: "code-review",
          name: "code-review",
          description: "Review code",
        },
      ],
    };
  });

  async function pickCodeReview(user: ReturnType<typeof setupUser>) {
    await user.type(screen.getByRole("textbox"), "use @co");
    await user.click(await screen.findByTestId("skill-picker-row-code-review"));
  }

  function skillTiles() {
    return screen
      .getByRole("textbox")
      .querySelectorAll('[data-mention-type="skill"]');
  }

  test("opens on `@` with the chat skills that start with the query", async () => {
    render(<Composer />);
    const user = setupUser();
    const input = screen.getByRole("textbox");

    await user.type(input, "costs $co (@co");
    expect(screen.queryByTestId("skill-picker-popover")).toBeNull();

    await user.type(input, " or @Co");
    expect(await screen.findByTestId("skill-picker-popover")).toHaveTextContent(
      "@code-review"
    );
    await user.type(input, "x");
    expect(screen.queryByTestId("skill-picker-popover")).toBeNull();
  });

  test("fetches the chat skills again when the input gains focus, not on a window focus", async () => {
    mockChatSkills = null;
    let skills: ChatSkill[] = [];
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockImplementation(async () => new Response(JSON.stringify(skills)));
    try {
      const skillFetches = () =>
        fetchSpy.mock.calls.filter(([url]) => url === "/api/skills/chat")
          .length;
      render(<Composer />);
      await waitFor(() => expect(skillFetches()).toBe(1));

      // A skill made in another tab or by another user.
      skills = [
        {
          name: "code-review",
          description: "Review code",
          short_description: null,
          version_id: "v1",
          built_in_skill_id: null,
        },
      ];
      await act(async () => {
        window.dispatchEvent(new Event("focus"));
      });
      expect(skillFetches()).toBe(1);

      // The composer takes focus after each send, so a focus within a minute
      // of the last fetch does not fetch.
      const firstFetchAt = Date.now();
      const nowSpy = jest
        .spyOn(Date, "now")
        .mockReturnValue(firstFetchAt + 59_000);
      const input = screen.getByRole("textbox");
      act(() => {
        input.blur();
        input.focus();
      });
      await act(async () => {});
      expect(skillFetches()).toBe(1);

      nowSpy.mockReturnValue(firstFetchAt + 61_000);
      act(() => {
        input.blur();
        input.focus();
      });
      await waitFor(() => expect(skillFetches()).toBe(2));
      const user = setupUser();
      await user.type(input, "use @co");
      expect(
        await screen.findByTestId("skill-picker-row-code-review")
      ).toBeVisible();
    } finally {
      jest.restoreAllMocks();
    }
  });

  test("keeps the input focus handler while the chat skills fetch", async () => {
    mockChatSkills = null;
    const response = deferred<Response>();
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockImplementation(() => response.promise);
    try {
      const { result } = renderHook(() => useChatSkills({ builtIns: true }), {
        wrapper: ({ children }) => (
          <SWRConfig value={{ provider: () => new Map() }}>
            {children}
          </SWRConfig>
        ),
      });
      const { onInputFocus } = result.current;
      await act(async () => {
        response.resolve(new Response(JSON.stringify([])));
      });
      expect(fetchSpy).toHaveBeenCalledTimes(1);
      expect(result.current.onInputFocus).toBe(onInputFocus);
    } finally {
      fetchSpy.mockRestore();
    }
  });

  test("a row shows the skill's short description when it has one", async () => {
    mockChatSkills = null;
    const skills: ChatSkill[] = [
      {
        name: "code-review",
        description: "Review code for bugs, style and missing tests",
        short_description: "Review code",
        version_id: "v1",
        built_in_skill_id: null,
      },
      {
        name: "commit-message",
        description: "Write a commit message",
        short_description: null,
        version_id: "v2",
        built_in_skill_id: null,
      },
    ];
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockImplementation(async () => new Response(JSON.stringify(skills)));
    try {
      render(<Composer />);
      const user = setupUser();
      await user.type(screen.getByRole("textbox"), "use @co");

      const shortRow = await screen.findByTestId(
        "skill-picker-row-code-review"
      );
      expect(shortRow).toHaveTextContent("Review code");
      expect(shortRow).not.toHaveTextContent("missing tests");
      expect(
        screen.getByTestId("skill-picker-row-commit-message")
      ).toHaveTextContent("Write a commit message");
    } finally {
      fetchSpy.mockRestore();
    }
  });

  test.each([
    [false, true],
    [true, false],
  ])(
    "with incognito %s, the picker offers built-ins: %s",
    async (incognito, offersBuiltIns) => {
      mockChatSkills = null;
      mockIncognitoEnabled = incognito;
      const skills: ChatSkill[] = [
        {
          name: "pptx",
          description: "Make decks",
          short_description: null,
          version_id: "b1",
          built_in_skill_id: "pptx",
        },
        {
          name: "plan",
          description: "Plan work",
          short_description: null,
          version_id: "v1",
          built_in_skill_id: null,
        },
      ];
      const fetchSpy = jest
        .spyOn(global, "fetch")
        .mockImplementation(async () => new Response(JSON.stringify(skills)));
      try {
        render(<Composer />);
        const user = setupUser();
        await user.type(screen.getByRole("textbox"), "use @p");

        await screen.findByTestId("skill-picker-row-plan");
        if (offersBuiltIns) {
          expect(screen.getByTestId("skill-picker-row-pptx")).toBeVisible();
        } else {
          expect(screen.queryByTestId("skill-picker-row-pptx")).toBeNull();
        }
      } finally {
        fetchSpy.mockRestore();
      }
    }
  );

  test("at the mention limit, it offers only the skills already picked", async () => {
    const names = Array.from(
      { length: MAX_MENTIONS_PER_MESSAGE + 1 },
      (_, index) => `skill-${String(index).padStart(2, "0")}`
    );
    mockChatSkills = {
      ...NO_SKILLS,
      skills: names.map((name) => ({
        kind: "skill",
        slug: name,
        name,
        description: name,
      })),
    };
    const picked = names.slice(0, MAX_MENTIONS_PER_MESSAGE);
    const inputBarRef = createRef<AppInputBarHandle>();
    render(<Composer inputBarRef={inputBarRef} />);
    act(() =>
      inputBarRef.current?.restore({
        message: picked.map((name) => `@${name}`).join(" "),
        mentions: picked.map((name) => ({ type: "skill", name })),
        files: [],
      })
    );
    expect(skillTiles()).toHaveLength(MAX_MENTIONS_PER_MESSAGE);

    const user = setupUser();
    await user.keyboard(" @skill-");
    await screen.findByTestId("skill-picker-row-skill-00");
    expect(screen.queryByTestId("skill-picker-row-skill-20")).toBeNull();
    await user.keyboard("2");
    expect(screen.queryByTestId("skill-picker-popover")).toBeNull();
  });

  /** Clicks the input's text with the caret before character `offset`.
   * user-event ignores a pointer offset in a contentEditable. */
  function clickAt(offset: number) {
    const input = screen.getByRole("textbox");
    const text = input.firstChild;
    if (!(text instanceof Text)) throw new Error("Expected one text node");
    fireEvent.mouseDown(input);
    window.getSelection()?.collapse(text, offset);
    fireEvent.mouseUp(input);
  }

  test("a click inside a word that matches nothing does not open it", async () => {
    render(<Composer />);
    const user = setupUser();
    await user.type(screen.getByRole("textbox"), "@codebar");
    expect(screen.queryByTestId("skill-picker-popover")).toBeNull();

    await user.click(document.body);
    clickAt("@code".length);
    expect(screen.queryByTestId("skill-picker-popover")).toBeNull();
  });

  test("the query is the whole word around the caret", async () => {
    const onSubmit = jest.fn();
    render(<Composer onSubmit={onSubmit} />);
    const user = setupUser();
    await user.type(screen.getByRole("textbox"), "@codebar");
    clickAt("@code".length);

    // `@cod|bar` searches for `codbar`, which matches nothing.
    await user.keyboard("{Backspace}");
    expect(screen.queryByTestId("skill-picker-popover")).toBeNull();
    await user.keyboard("{Enter}");
    expect(skillTiles()).toHaveLength(0);
    expect(onSubmit).toHaveBeenCalledWith({
      message: "@codbar",
      mentions: [],
    });
  });

  test("deleting the rest of a word opens it on the match", async () => {
    render(<Composer />);
    const user = setupUser();
    await user.type(screen.getByRole("textbox"), "@codebar");
    await user.keyboard("{Backspace}{Backspace}{Backspace}");
    expect(await screen.findByTestId("skill-picker-popover")).toHaveTextContent(
      "@code-review"
    );
  });

  test("a caret move closes it and does not change its query", async () => {
    render(<Composer />);
    const user = setupUser();
    await user.type(screen.getByRole("textbox"), "@code");
    await screen.findByTestId("skill-picker-popover");

    await user.keyboard("{ArrowLeft}");
    expect(screen.queryByTestId("skill-picker-popover")).toBeNull();
    await user.keyboard("{ArrowRight}");
    expect(screen.queryByTestId("skill-picker-popover")).toBeNull();
  });

  test("a caret move without key or mouse events closes it", async () => {
    render(<Composer />);
    const user = setupUser();
    await user.type(screen.getByRole("textbox"), "@code");
    await screen.findByTestId("skill-picker-popover");
    // The `selectionchange` that follows the input keeps it open.
    await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
    expect(screen.getByTestId("skill-picker-popover")).toBeVisible();

    const text = screen.getByRole("textbox").firstChild;
    if (!(text instanceof Text)) throw new Error("Expected one text node");
    act(() => window.getSelection()?.collapse(text, 1));
    await waitFor(() =>
      expect(screen.queryByTestId("skill-picker-popover")).toBeNull()
    );
  });

  test("Esc hides it until its `@` is deleted", async () => {
    render(<Composer />);
    const user = setupUser();
    await user.type(screen.getByRole("textbox"), "@co");
    await screen.findByTestId("skill-picker-popover");

    await user.keyboard("{Escape}d");
    expect(screen.queryByTestId("skill-picker-popover")).toBeNull();
    await user.keyboard("{Backspace}{Backspace}{Backspace}{Backspace}@co");
    expect(await screen.findByTestId("skill-picker-popover")).toBeVisible();
  });

  test("a click in the input closes it without hiding the word", async () => {
    render(<Composer />);
    const user = setupUser();
    const input = screen.getByRole("textbox");
    await user.type(input, "@cod");
    await screen.findByTestId("skill-picker-popover");
    // The menu listens for outside pointer downs after it opens.
    await act(() => new Promise((resolve) => setTimeout(resolve, 0)));

    fireEvent.pointerDown(input);
    expect(screen.queryByTestId("skill-picker-popover")).toBeNull();
    await user.keyboard("e");
    expect(await screen.findByTestId("skill-picker-popover")).toBeVisible();
  });

  test("a pick by Enter replaces the whole word around the caret", async () => {
    const onSubmit = jest.fn();
    render(<Composer onSubmit={onSubmit} />);
    const user = setupUser();
    await user.type(screen.getByRole("textbox"), "use @cde");
    clickAt("use @c".length);
    await user.keyboard("o");
    expect(await screen.findByTestId("skill-picker-popover")).toBeVisible();

    await user.keyboard("{Enter}");
    expect(skillTiles()).toHaveLength(1);
    expect(screen.getByRole("textbox")).toHaveTextContent(/^use @code-review$/);
    await user.keyboard("now{Enter}");
    expect(onSubmit).toHaveBeenCalledWith({
      message: "use @code-review now",
      mentions: [{ type: "skill", name: "code-review", index: 4 }],
    });
  });

  test("the arrow keys reach Manage skills, and Enter opens the Skills tab", async () => {
    render(<Composer />);
    const user = setupUser();
    await user.type(screen.getByRole("textbox"), "use @co");
    expect(await screen.findByTestId("skill-picker-popover")).toBeVisible();

    await user.keyboard("{ArrowUp}{Enter}");
    expect(window.location.pathname).toBe("/app/customize/skills");
    expect(skillTiles()).toHaveLength(0);
  });

  test("hides the `/` prompt shortcuts while it is open", async () => {
    render(<Composer />);
    const user = setupUser();
    const input = screen.getByRole("textbox");

    await user.type(input, "/foo");
    expect(await screen.findByText("Create New Prompt")).toBeVisible();

    await user.type(input, " @co");
    expect(await screen.findByTestId("skill-picker-popover")).toBeVisible();
    expect(screen.queryByText("Create New Prompt")).toBeNull();
  });

  test("a pick becomes a tile that sends its skill with the message", async () => {
    const onSubmit = jest.fn();
    render(<Composer onSubmit={onSubmit} />);
    const user = setupUser();

    await pickCodeReview(user);
    expect(skillTiles()).toHaveLength(1);
    await user.type(screen.getByRole("textbox"), "now{Enter}");

    expect(onSubmit).toHaveBeenCalledWith({
      message: "use @code-review now",
      mentions: [{ type: "skill", name: "code-review", index: 4 }],
    });
  });

  test("an IME Enter does not pick", async () => {
    render(<Composer />);
    const user = setupUser();
    await user.type(screen.getByRole("textbox"), "use @co");
    await screen.findByTestId("skill-picker-popover");

    act(() => {
      document.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", isComposing: true })
      );
    });
    expect(skillTiles()).toHaveLength(0);
    expect(screen.getByTestId("skill-picker-popover")).toBeVisible();
  });

  test("the caret after a tile does not reopen the picker on its text", async () => {
    render(<Composer />);
    const user = setupUser();

    await pickCodeReview(user);
    await user.type(screen.getByRole("textbox"), "{Backspace}");
    expect(screen.queryByTestId("skill-picker-popover")).toBeNull();
  });

  test("undoing a tile's removal restores its skill", async () => {
    const onSubmit = jest.fn();
    render(<Composer onSubmit={onSubmit} />);
    const user = setupUser();
    await pickCodeReview(user);

    const remove = screen
      .getByRole("textbox")
      .querySelector("[data-rich-tile-remove]");
    if (!remove) throw new Error("The tile has no remove button");
    await user.pointer({ keys: "[MouseLeft>]", target: remove });
    expect(skillTiles()).toHaveLength(0);

    await user.keyboard("{Control>}z{/Control}");
    expect(skillTiles()).toHaveLength(1);
    await user.type(screen.getByRole("textbox"), "{Enter}");
    expect(onSubmit).toHaveBeenCalledWith({
      message: "use @code-review ",
      mentions: [{ type: "skill", name: "code-review", index: 4 }],
    });
  });

  test("cut and pasted mention text is not a pick", async () => {
    const onSubmit = jest.fn();
    render(<Composer onSubmit={onSubmit} />);
    const user = setupUser();
    await pickCodeReview(user);
    const input = screen.getByRole("textbox");

    window.getSelection()!.selectAllChildren(input);
    let cutText = "";
    fireEvent.cut(input, {
      clipboardData: {
        setData: (_type: string, text: string) => (cutText = text),
      },
    });
    expect(cutText).toBe("use @code-review ");
    expect(input).toHaveTextContent(/^$/);
    await user.paste(cutText);
    expect(input).toHaveTextContent("use @code-review");
    expect(skillTiles()).toHaveLength(0);

    await user.type(input, "now{Enter}");
    expect(onSubmit).toHaveBeenCalledWith({
      message: "use @code-review now",
      mentions: [],
    });
  });

  test("a restored draft keeps its picks as tiles", async () => {
    jest.useFakeTimers();
    try {
      const user = setupUser({ advanceTimers: jest.advanceTimersByTime });
      const { unmount } = render(<Composer />);
      await pickCodeReview(user);
      // The draft saves after a delay.
      act(() => jest.advanceTimersByTime(300));
      unmount();

      const onSubmit = jest.fn();
      render(<Composer onSubmit={onSubmit} />);
      expect(screen.getByRole("textbox")).toHaveTextContent("use @code-review");
      expect(skillTiles()).toHaveLength(1);
      await user.type(screen.getByRole("textbox"), "now{Enter}");

      expect(onSubmit).toHaveBeenCalledWith({
        message: "use @code-review now",
        mentions: [{ type: "skill", name: "code-review", index: 4 }],
      });
    } finally {
      jest.useRealTimers();
    }
  });

  /** Puts the caret before character `offset` of the input's first text
   * node. */
  function caretAt(offset: number) {
    const text = screen.getByRole("textbox").firstChild;
    if (!(text instanceof Text)) throw new Error("Expected a text node first");
    act(() => window.getSelection()?.collapse(text, offset));
  }

  // Each composition is sent, then saved as a draft and restored, then put
  // back after a failed send; every time the tiles stay where they were.
  test.each<
    [
      string,
      (user: ReturnType<typeof setupUser>) => Promise<void>,
      ComposedMessage,
    ]
  >([
    [
      "a tile with `(` before it and a word typed against it",
      async (user) => {
        await pickCodeReview(user);
        await user.type(screen.getByRole("textbox"), "{Backspace}now)");
        caretAt("use ".length);
        await user.keyboard("(");
      },
      {
        message: "use (@code-reviewnow)",
        mentions: [{ type: "skill", name: "code-review", index: 5 }],
      },
    ],
    [
      "typed `@name` text beside a tile of the same skill",
      async (user) => {
        await user.paste("@code-review vs ");
        await pickCodeReview(user);
      },
      {
        message: "@code-review vs use @code-review ",
        mentions: [{ type: "skill", name: "code-review", index: 20 }],
      },
    ],
  ])(
    "%s survives the draft and a failed send",
    async (_name, compose, expected) => {
      jest.useFakeTimers();
      try {
        const user = setupUser({ advanceTimers: jest.advanceTimersByTime });
        const first = render(<Composer />);
        await compose(user);
        expect(skillTiles()).toHaveLength(expected.mentions.length);
        // The draft saves after a delay.
        act(() => jest.advanceTimersByTime(300));
        first.unmount();

        const inputBarRef = createRef<AppInputBarHandle>();
        const onSubmit = jest.fn(() => inputBarRef.current?.reset());
        render(<Composer inputBarRef={inputBarRef} onSubmit={onSubmit} />);
        expect(skillTiles()).toHaveLength(expected.mentions.length);
        await user.type(screen.getByRole("textbox"), "{Enter}");
        expect(onSubmit).toHaveBeenLastCalledWith(expected);

        act(() => inputBarRef.current?.restore({ ...expected, files: [] }));
        expect(skillTiles()).toHaveLength(expected.mentions.length);
        await user.type(screen.getByRole("textbox"), "{Enter}");
        expect(onSubmit).toHaveBeenCalledTimes(2);
        expect(onSubmit).toHaveBeenLastCalledWith(expected);
      } finally {
        jest.useRealTimers();
      }
    }
  );

  test("voice input keeps the tiles, and its auto-send sends them", async () => {
    mockSttEnabled = true;
    const onSubmit = jest.fn();
    render(<Composer onSubmit={onSubmit} />);
    await pickCodeReview(setupUser());

    const microphone = mockMicrophone;
    if (!microphone) throw new Error("The microphone button did not render");
    act(() => microphone.onTranscription("use @code-review  please"));
    expect(screen.getByRole("textbox")).toHaveTextContent(
      "use @code-review please"
    );
    expect(skillTiles()).toHaveLength(1);

    act(() => microphone.onAutoSend?.("use @code-review  please now"));
    expect(onSubmit).toHaveBeenCalledWith({
      message: "use @code-review  please now",
      mentions: [{ type: "skill", name: "code-review", index: 4 }],
    });
  });

  test("voice auto-send drops a mention whose tile the transcript removed", async () => {
    mockSttEnabled = true;
    const onSubmit = jest.fn();
    render(<Composer onSubmit={onSubmit} />);
    await pickCodeReview(setupUser());

    const microphone = mockMicrophone;
    if (!microphone) throw new Error("The microphone button did not render");
    act(() => microphone.onAutoSend?.("review this please"));
    expect(onSubmit).toHaveBeenCalledWith({
      message: "review this please",
      mentions: [],
    });
  });
});
