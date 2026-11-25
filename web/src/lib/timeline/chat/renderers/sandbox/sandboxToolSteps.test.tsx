import { act, render, screen, waitFor, within } from "@tests/setup/test-utils";
import { Message } from "@/app/app/types";
import { upsertMessages } from "@/app/app/services/messageTree";
import {
  FileToolName,
  ObjTypes,
  Packet,
  PacketType,
  Placement,
  StopReason,
} from "@/app/app/services/streamingModels";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import AgentMessage from "@/app/app/message/messageComponents/AgentMessage";
import { FullChatState } from "@/app/app/message/messageComponents/types";
import type { MinimalAgent } from "@/lib/agents/types";

jest.mock("@/providers/VoiceModeProvider", () => ({
  useVoiceMode: () => ({
    resetTTS: jest.fn(),
    streamTTS: jest.fn(),
    stopTTS: jest.fn(),
    revealedCharCount: 0,
    autoPlayback: false,
    isAudioSyncActive: false,
    activeMessageNodeId: null,
    isAwaitingAutoPlaybackStart: false,
  }),
}));

const SESSION_ID = "session-1";
const USER_NODE_ID = 1;
const ANSWER_NODE_ID = 2;

const agent: MinimalAgent = {
  id: 0,
  name: "Default Chat",
  description: "",
  tools: [],
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
const chatState: FullChatState = { agent };

const at =
  (placement: Placement) =>
  (obj: ObjTypes): Packet => ({ placement, obj });

const sectionEnd: ObjTypes = { type: PacketType.SECTION_END };

/** Matches the element whose whole text, its children's included, is `text`:
 * a status names its path in a code element. */
function wholeText(text: string) {
  return (_content: string, element: Element | null) =>
    element?.textContent === text &&
    Array.from(element.children).every((child) => child.textContent !== text);
}

function answer(turn_index: number): Packet[] {
  const packet = at({ turn_index, tab_index: 0 });
  return [
    packet({
      type: PacketType.MESSAGE_START,
      id: "answer",
      content: "",
      final_documents: null,
    }),
    packet({ type: PacketType.MESSAGE_DELTA, content: "Done." }),
    packet({ type: PacketType.STOP, stop_reason: StopReason.FINISHED }),
  ];
}

function renderMessage(packets: Packet[]) {
  return (
    <AgentMessage
      rawPackets={packets}
      packetCount={packets.length}
      chatState={chatState}
      nodeId={ANSWER_NODE_ID}
      llmManager={null}
      hideFooter
      disableTTS
    />
  );
}

// Opens the run card when it is folded, then its steps, which start closed.
// The card's fold button is named by the step count.
async function openRun() {
  const fold = screen.queryByRole("button", { name: /^\d+ steps?$/ });
  if (fold?.getAttribute("aria-expanded") === "false") {
    await act(async () => fold.click());
  }
  for (const step of screen.queryAllByRole("button", { expanded: false })) {
    await act(async () => step.click());
  }
}

async function expandTimeline() {
  await screen.findByText("Done.");
  await openRun();
}

const PATCH = [
  "*** Begin Patch",
  "*** Add File: new.py",
  "+print('hi')",
  "*** Update File: old.py",
  "*** Move to: moved.py",
  "@@",
  "-a = 1",
  "+a = 2",
  "*** End Patch",
].join("\n");

beforeEach(() => {
  const messageTree = upsertMessages(
    new Map(),
    [USER_NODE_ID, ANSWER_NODE_ID].map(
      (nodeId): Message => ({
        nodeId,
        parentNodeId: nodeId === USER_NODE_ID ? null : USER_NODE_ID,
        type: nodeId === USER_NODE_ID ? "user" : "assistant",
        message: "",
        files: [],
        toolCall: null,
        packets: [],
      })
    ),
    true
  );
  const store = useChatSessionStore.getState();
  store.createSession(SESSION_ID, { messageTree, chatState: "input" });
  store.setCurrentSession(SESSION_ID);
});

afterEach(() => {
  useChatSessionStore.setState({ currentSessionId: null, sessions: new Map() });
});

test("a command shows its output while it runs and how it ended", async () => {
  const call = at({ turn_index: 0, tab_index: 0 });
  const running = [
    call({
      type: PacketType.EXEC_COMMAND_START,
      cmd: "make test",
      workdir: "/home/onyx/workspaces/abc",
    }),
    call({ type: PacketType.EXEC_OUTPUT_DELTA, text: "collecting\n" }),
    ...Array.from({ length: 8 }, (_, index) =>
      call({
        type: PacketType.EXEC_OUTPUT_DELTA,
        text: `test_${index + 1} ok\n`,
      })
    ),
  ];
  const view = render(renderMessage(running));
  try {
    expect(
      (await screen.findAllByText("Running command")).length
    ).toBeGreaterThan(0);
    await openRun();
    expect(view.container).toHaveTextContent("$ make test");
    // While it runs, only the last lines of the output are in the page.
    expect(screen.getByText(/test_8 ok/)).toBeInTheDocument();
    expect(view.container).not.toHaveTextContent("collecting");

    // The saved output is what the model saw, cut by tokens; it replaces the
    // live preview.
    view.rerender(
      renderMessage([
        ...running,
        call({ type: PacketType.EXEC_OUTPUT_DELTA, text: "test_9 ok\n" }),
        call({
          type: PacketType.EXEC_END,
          exit_code: 2,
          completion: "exited",
          session_id: null,
          wall_time_seconds: 1.5,
          truncated: true,
          output: "collecting\n…12 tokens truncated…\n1 failed\n",
          error: null,
        }),
        call(sectionEnd),
        ...answer(1),
      ])
    );
    await expandTimeline();
    expect(screen.getByText("Ran command")).toBeInTheDocument();
    expect(
      screen.getByText("In /home/onyx/workspaces/abc")
    ).toBeInTheDocument();
    expect(
      screen.getByText(/collecting\s+…12 tokens truncated…\s+1 failed/)
    ).toBeInTheDocument();
    expect(view.container).not.toHaveTextContent("test_9 ok");
    expect(screen.getByText("Exit code 2")).toBeInTheDocument();
    expect(screen.getByText("Output truncated")).toBeInTheDocument();
  } finally {
    view.unmount();
  }
});

test("session input shows typed keys, and polls show the session state", async () => {
  const sent = at({ turn_index: 0, tab_index: 0 });
  const polled = at({ turn_index: 1, tab_index: 0 });
  const failed = at({ turn_index: 2, tab_index: 0 });
  const failedInput = at({ turn_index: 3, tab_index: 0 });
  const started = at({ turn_index: 4, tab_index: 0 });
  const end = {
    type: PacketType.EXEC_END,
    exit_code: null,
    wall_time_seconds: 0.2,
    truncated: false,
    output: "",
    error: null,
  } as const;
  const view = render(
    renderMessage([
      sent({
        type: PacketType.WRITE_STDIN_START,
        session_id: "7",
        chars: "\u0003",
      }),
      sent({ ...end, completion: null, session_id: "7" }),
      sent(sectionEnd),
      polled({
        type: PacketType.WRITE_STDIN_START,
        session_id: "7",
        chars: "",
      }),
      polled({
        ...end,
        completion: "signaled",
        session_id: null,
        output: "^C received",
      }),
      polled(sectionEnd),
      failed({ type: PacketType.EXEC_COMMAND_START, cmd: "ls", workdir: null }),
      failed({
        ...end,
        completion: null,
        session_id: null,
        output: null,
        error: "Sandbox is unavailable",
      }),
      failed(sectionEnd),
      failedInput({
        type: PacketType.WRITE_STDIN_START,
        session_id: "9",
        chars: "y\n",
      }),
      failedInput({
        ...end,
        completion: null,
        session_id: null,
        output: null,
        error: "Session 9 has ended",
      }),
      failedInput(sectionEnd),
      started({
        type: PacketType.EXEC_COMMAND_START,
        cmd: "npm run dev",
        workdir: null,
      }),
      started({ ...end, completion: null, session_id: "12" }),
      started(sectionEnd),
      ...answer(5),
    ])
  );
  try {
    await expandTimeline();
    expect(screen.getByText("Sent input to session 7")).toBeInTheDocument();
    expect(screen.getByText("^C")).toBeInTheDocument();
    expect(screen.getByText("Still running (session 7)")).toBeInTheDocument();
    expect(screen.getByText("Checked session 7")).toBeInTheDocument();
    expect(screen.getByText("Stopped by a signal")).toBeInTheDocument();
    expect(screen.getByText("Command failed")).toBeInTheDocument();
    expect(screen.getByText("Sandbox is unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("Could not send input to session 9")
    ).toBeInTheDocument();
    expect(screen.getByText("Session 9 has ended")).toBeInTheDocument();
    // A command still running at its end has only started.
    expect(screen.getByText("Started command")).toBeInTheDocument();
    expect(screen.getByText("Still running (session 12)")).toBeInTheDocument();
  } finally {
    view.unmount();
  }
});

// Renderer contract: the backend renderer starts a write_stdin call whose
// arguments are wrong-typed with an empty session ID.
test("a session call without a session ID leaves the session out", async () => {
  const call = at({ turn_index: 0, tab_index: 0 });
  const view = render(
    renderMessage([
      call({ type: PacketType.WRITE_STDIN_START, session_id: "", chars: "" }),
      call({
        type: PacketType.EXEC_END,
        exit_code: null,
        wall_time_seconds: null,
        truncated: false,
        output: null,
        completion: null,
        session_id: null,
        error: "session_id: Input should be a valid string",
      }),
      call(sectionEnd),
      ...answer(1),
    ])
  );
  try {
    await expandTimeline();
    expect(screen.getByText("Could not check the session")).toBeInTheDocument();
  } finally {
    view.unmount();
  }
});

test("a patch lists the files it changed, and a failed patch says why", async () => {
  const applied = at({ turn_index: 0, tab_index: 0 });
  const rejected = at({ turn_index: 1, tab_index: 0 });
  const view = render(
    renderMessage([
      applied({
        type: PacketType.APPLY_PATCH_START,
        patch: PATCH,
        tool_name: "apply_patch",
      }),
      applied({
        type: PacketType.APPLY_PATCH_END,
        files: [
          { path: "new.py", change: "add", move_path: null },
          { path: "old.py", change: "update", move_path: "moved.py" },
        ],
        error: null,
      }),
      applied(sectionEnd),
      rejected({
        type: PacketType.APPLY_PATCH_START,
        patch: PATCH,
        tool_name: "apply_patch",
      }),
      rejected({
        type: PacketType.APPLY_PATCH_END,
        files: [],
        error: "Failed to find expected lines in old.py",
      }),
      rejected(sectionEnd),
      ...answer(2),
    ])
  );
  try {
    await expandTimeline();
    expect(screen.getByText("Edited 2 files")).toBeInTheDocument();
    expect(screen.getByText("new.py")).toBeInTheDocument();
    expect(
      screen.getByText(wholeText("old.py → moved.py"))
    ).toBeInTheDocument();
    // The card lays out only the head of each patch.
    expect(screen.getAllByText(/\+print\('hi'\)/)).toHaveLength(2);
    expect(screen.queryByText(/\+a = 2/)).not.toBeInTheDocument();
    expect(screen.getByText("Edit failed")).toBeInTheDocument();
    expect(
      screen.getByText("Failed to find expected lines in old.py")
    ).toBeInTheDocument();
  } finally {
    view.unmount();
  }
});

function fileProgress(tool_name: FileToolName, paths: string[]): ObjTypes {
  return { type: PacketType.FILE_TOOL_PROGRESS, tool_name, paths };
}

/** The text of a message's steps, from `from` on: the run header measures
 * the live thinking time, which the steps do not depend on. */
async function stepsText(packets: Packet[], from: string): Promise<string> {
  const view = render(renderMessage(packets));
  try {
    await openRun();
    await screen.findAllByText(from);
    const text = view.container.textContent ?? "";
    return text.slice(text.indexOf(from));
  } finally {
    view.unmount();
  }
}

test("a write shows its progress while it streams, then the replayed card", async () => {
  const call = at({ turn_index: 0, tab_index: 0 });
  const streaming = [
    call(fileProgress("write", [])),
    call(fileProgress("write", ["report.md"])),
  ];
  const finished = [
    call({
      type: PacketType.APPLY_PATCH_START,
      patch:
        "*** Begin Patch\n*** Add File: report.md\n+# Report\n*** End Patch",
      tool_name: "write",
    }),
    call({
      type: PacketType.APPLY_PATCH_END,
      files: [{ path: "report.md", change: "add", move_path: null }],
      error: null,
    }),
    call(sectionEnd),
    ...answer(1),
  ];
  const replayed = await stepsText(finished, "Edited 1 file");

  const view = render(renderMessage(streaming));
  try {
    const progress = wholeText("Writing report.md…");
    expect((await screen.findAllByText(progress)).length).toBeGreaterThan(0);

    // The start packet alone replaces the progress line.
    view.rerender(renderMessage([...streaming, ...finished.slice(0, 1)]));
    await openRun();
    expect(view.container).not.toHaveTextContent("Writing");
  } finally {
    view.unmount();
  }
  expect(await stepsText([...streaming, ...finished], "Edited 1 file")).toBe(
    replayed
  );
});

test("a patch names its files while it streams, then matches its replay", async () => {
  const call = at({ turn_index: 0, tab_index: 0 });
  const streaming = [
    call(fileProgress("apply_patch", [])),
    call(fileProgress("apply_patch", ["new.py", "old.py"])),
  ];
  const finished = [
    call({
      type: PacketType.APPLY_PATCH_START,
      patch: PATCH,
      tool_name: "apply_patch",
    }),
    call({
      type: PacketType.APPLY_PATCH_END,
      files: [
        { path: "new.py", change: "add", move_path: null },
        { path: "old.py", change: "update", move_path: "moved.py" },
      ],
      error: null,
    }),
    call(sectionEnd),
    ...answer(1),
  ];
  const view = render(renderMessage(streaming));
  try {
    await screen.findAllByText("Patching 2 files…");
    await openRun();
    expect(screen.getByText("new.py")).toBeInTheDocument();
    expect(screen.getByText("old.py")).toBeInTheDocument();
  } finally {
    view.unmount();
  }
  expect(await stepsText([...streaming, ...finished], "Edited 2 files")).toBe(
    await stepsText(finished, "Edited 2 files")
  );
});

test("an edit names its file", async () => {
  const view = render(
    renderMessage([
      at({ turn_index: 0, tab_index: 0 })(fileProgress("edit", ["src/app.py"])),
    ])
  );
  try {
    expect(
      (await screen.findAllByText(wholeText("Editing src/app.py…"))).length
    ).toBeGreaterThan(0);
  } finally {
    view.unmount();
  }
});

/** Turns motion on, which jsdom's setup reduces, so a title that swaps
 * through an animation would keep its old text and element. */
function allowMotion() {
  return jest.spyOn(window, "matchMedia").mockImplementation(
    (query) =>
      ({
        matches: false,
        media: query,
        addEventListener: jest.fn(),
        removeEventListener: jest.fn(),
      }) as unknown as MediaQueryList
  );
}

test("a call names its file once the path arrives, in the same title element", async () => {
  const motion = allowMotion();
  const call = at({ turn_index: 0, tab_index: 0 });
  const view = render(renderMessage([call(fileProgress("edit", []))]));
  try {
    const titles = await screen.findAllByText("Editing a file…");
    // A remounted title would restart its animation.
    view.rerender(renderMessage([call(fileProgress("edit", ["src/app.py"]))]));
    for (const title of titles) {
      await waitFor(() =>
        expect(title).toHaveTextContent("Editing src/app.py…")
      );
      expect(title).toBeInTheDocument();
    }
  } finally {
    view.unmount();
    motion.mockRestore();
  }
});

test("sandbox text is isolated in markup, and paths show without bidi controls", async () => {
  // A path that closes an isolate early, then overrides the direction.
  const path = "a\u2069\u202Eb.py";
  const streaming = at({ turn_index: 0, tab_index: 0 });
  const patched = at({ turn_index: 1, tab_index: 0 });
  const published = at({ turn_index: 2, tab_index: 0 });
  const view = render(
    renderMessage([
      patched({
        type: PacketType.APPLY_PATCH_START,
        patch: `*** Begin Patch\n*** Add File: ${path}\n+x\n*** End Patch`,
        tool_name: "apply_patch",
      }),
      patched({
        type: PacketType.APPLY_PATCH_END,
        files: [{ path, change: "add", move_path: null }],
        error: `Could not write ${path}`,
      }),
      patched(sectionEnd),
      published({
        type: PacketType.PUBLISH_FILES_START,
        files: [{ path: `out/${path}`, title: "\u202Bnotes" }],
        description: null,
      }),
      streaming(fileProgress("write", [path])),
    ])
  );
  try {
    // Displayed paths and labels drop their bidi controls, and markup
    // isolates them, so copied text has no hidden characters.
    expect(
      (await screen.findAllByText(wholeText("Writing ab.py…"))).length
    ).toBeGreaterThan(0);
    for (const code of screen.getAllByText("ab.py", { selector: "code" })) {
      expect(code).toHaveAttribute("dir", "ltr");
    }
    await openRun();
    expect(screen.getByText("ab.py", { selector: "span" })).toHaveAttribute(
      "dir",
      "ltr"
    );
    expect(screen.getByText("out/ab.py")).toHaveAttribute("dir", "ltr");
    expect(screen.getByText("notes")).toHaveAttribute("dir", "auto");
    // The patch and the error keep the sandbox's text, inside an isolate.
    expect(
      screen.getByText(`*** Add File: ${path}`).closest("[dir]")
    ).toHaveAttribute("dir", "ltr");
    const error = screen.getByText(`Could not write ${path}`);
    expect(error).toHaveAttribute("dir", "ltr");
    // The error's paragraph keeps the page's direction.
    expect(error.closest("p")).not.toHaveAttribute("dir");
  } finally {
    view.unmount();
  }
});

test("a patch stopped while it streams shows only that it stopped, as on replay", async () => {
  const call = at({ turn_index: 0, tab_index: 0 });
  const stop = at({ turn_index: 1, tab_index: 0 })({
    type: PacketType.STOP,
    stop_reason: StopReason.USER_CANCELLED,
  });
  const progress = call(fileProgress("apply_patch", ["new.py"]));
  // A stop before the call's start: the live card keeps no partial progress.
  const view = render(renderMessage([progress, stop]));
  try {
    await openRun();
    expect((await screen.findAllByText("Stopped")).length).toBeGreaterThan(0);
    expect(screen.queryByText("new.py")).not.toBeInTheDocument();
    expect(screen.queryByText(/Patching/)).not.toBeInTheDocument();
  } finally {
    view.unmount();
  }
  // The stopped call's start and end follow its progress live; replay sends
  // them alone.
  const stopped = [
    call({
      type: PacketType.APPLY_PATCH_START,
      patch: "*** Begin Patch\n*** Add File: new.py\n+x",
      tool_name: "apply_patch",
    }),
    call(sectionEnd),
    stop,
  ];
  expect(await stepsText([progress, ...stopped], "Stopped")).toBe(
    await stepsText(stopped, "Stopped")
  );
});

test("a patch whose call fails after its progress shows only the error", async () => {
  const call = at({ turn_index: 0, tab_index: 0 });
  const view = render(
    renderMessage([
      call(fileProgress("apply_patch", ["new.py", "old.py"])),
      call({
        type: PacketType.APPLY_PATCH_START,
        patch: PATCH,
        tool_name: "apply_patch",
      }),
      call({
        type: PacketType.APPLY_PATCH_END,
        files: [],
        error: "Permission denied",
      }),
      call(sectionEnd),
      ...answer(1),
    ])
  );
  try {
    await expandTimeline();
    expect(screen.getByText("Edit failed")).toBeInTheDocument();
    expect(screen.getByText("Permission denied")).toBeInTheDocument();
    // The progress file list is gone.
    expect(screen.queryByText("new.py")).not.toBeInTheDocument();
    expect(screen.queryByText("old.py")).not.toBeInTheDocument();
  } finally {
    view.unmount();
  }
});

// Renderer contract: the backend renderer starts an edit whose arguments are
// wrong-typed with an empty patch, and ends it with the validation error.
test("an edit with wrong-typed arguments shows only that it failed and why", async () => {
  const call = at({ turn_index: 0, tab_index: 0 });
  const view = render(
    renderMessage([
      call({
        type: PacketType.APPLY_PATCH_START,
        patch: "",
        tool_name: "edit",
      }),
      call({
        type: PacketType.APPLY_PATCH_END,
        files: [],
        error: "file_path: Input should be a valid string",
      }),
      call(sectionEnd),
      ...answer(1),
    ])
  );
  try {
    await expandTimeline();
    expect(screen.getByText("Edit failed")).toBeInTheDocument();
    expect(
      screen.getByText("file_path: Input should be a valid string")
    ).toBeInTheDocument();
    expect(view.container).not.toHaveTextContent("*** Add File:");
    expect(screen.queryByText("Patch")).not.toBeInTheDocument();
  } finally {
    view.unmount();
  }
});

test("parallel edit and write calls render as separate steps", async () => {
  const edited = at({ turn_index: 0, tab_index: 0 });
  const written = at({ turn_index: 0, tab_index: 1 });
  const view = render(
    renderMessage([
      edited({
        type: PacketType.APPLY_PATCH_START,
        patch: PATCH,
        tool_name: "edit",
      }),
      edited(sectionEnd),
      written({
        type: PacketType.APPLY_PATCH_START,
        patch: PATCH,
        tool_name: "write",
      }),
      written(sectionEnd),
      ...answer(1),
    ])
  );
  try {
    await expandTimeline();
    // Each call is its own step with its own patch head.
    expect(screen.getAllByText(/\+print\('hi'\)/)).toHaveLength(2);
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  } finally {
    view.unmount();
  }
});

test("a cut patch head keeps a line past the view when the next line is blank", async () => {
  // A blank seventh line rendered as nothing, so the card saw no overflow
  // and hid the expand button.
  const patch = [
    "*** Begin Patch",
    "*** Update File: a.py",
    "@@",
    " one",
    "-two",
    "+TWO",
    "",
    " three",
    "*** End Patch",
  ].join("\n");
  const applied = at({ turn_index: 0, tab_index: 0 });
  const view = render(
    renderMessage([
      applied({
        type: PacketType.APPLY_PATCH_START,
        patch,
        tool_name: "apply_patch",
      }),
      applied({
        type: PacketType.APPLY_PATCH_END,
        files: [{ path: "a.py", change: "update", move_path: null }],
        error: null,
      }),
      applied(sectionEnd),
      ...answer(1),
    ])
  );
  try {
    await expandTimeline();
    const lines = screen.getByText("*** Begin Patch").parentElement?.children;
    expect(lines).toHaveLength(7);
    expect(screen.queryByText(/three/)).not.toBeInTheDocument();
  } finally {
    view.unmount();
  }
});

test("sandbox calls of a code mode program show as their own steps", async () => {
  const cell = { turn_index: 0, tab_index: 0 };
  const program = at(cell);
  const command = at({ ...cell, sub_turn_index: 0 });
  const patch = at({ ...cell, sub_turn_index: 1 });
  const view = render(
    renderMessage([
      program({ type: PacketType.CODE_MODE_START, code: "await run()" }),
      command({
        type: PacketType.EXEC_COMMAND_START,
        cmd: "pytest",
        workdir: null,
      }),
      // A replay sends no output deltas: the end carries the saved output.
      command({
        type: PacketType.EXEC_END,
        exit_code: 0,
        completion: "exited",
        session_id: null,
        wall_time_seconds: 2,
        truncated: false,
        output: "3 passed",
        error: null,
      }),
      command(sectionEnd),
      patch({
        type: PacketType.APPLY_PATCH_START,
        patch: PATCH,
        tool_name: "apply_patch",
      }),
      patch({
        type: PacketType.APPLY_PATCH_END,
        files: [{ path: "gone.py", change: "delete", move_path: null }],
        error: null,
      }),
      patch(sectionEnd),
      program({
        type: PacketType.CODE_MODE_DELTA,
        stdout: "",
        status: "completed",
        cell_id: 1,
        observation: 0,
      }),
      program(sectionEnd),
      ...answer(1),
    ])
  );
  try {
    await screen.findByText("Done.");
    await expandTimeline();
    expect(screen.getByText("Ran command")).toBeInTheDocument();
    expect(view.container).toHaveTextContent("$ pytest");
    expect(screen.getByText("3 passed")).toBeInTheDocument();
    expect(screen.getByText("Exit code 0")).toBeInTheDocument();
    expect(screen.getByText("Edited 1 file")).toBeInTheDocument();
    expect(screen.getByText("gone.py")).toBeInTheDocument();
    expect(view.container).not.toHaveTextContent(/await run/);
  } finally {
    view.unmount();
  }
});

test("a call that spans two code mode observations shows all its output", async () => {
  const cell = { turn_index: 0, tab_index: 0 };
  const waited = { turn_index: 1, tab_index: 0 };
  const command = (placement: Placement) =>
    at({ ...placement, sub_turn_index: 0 });
  const start: ObjTypes = {
    type: PacketType.EXEC_COMMAND_START,
    cmd: "make build",
    workdir: null,
  };
  const view = render(
    renderMessage([
      at(cell)({ type: PacketType.CODE_MODE_START, code: "await build()" }),
      command(cell)(start),
      command(cell)({ type: PacketType.EXEC_OUTPUT_DELTA, text: "step 1\n" }),
      at(cell)({
        type: PacketType.CODE_MODE_DELTA,
        stdout: "",
        status: "running",
        cell_id: 1,
        observation: 0,
      }),
      at(cell)(sectionEnd),
      // The later observation reports the call again, with only its own
      // deltas; the end carries the whole saved output.
      at(waited)({
        type: PacketType.CODE_MODE_START,
        code: "",
        cell_id: 1,
        observation: 1,
      }),
      command(waited)(start),
      command(waited)({
        type: PacketType.EXEC_OUTPUT_DELTA,
        text: "step 2\n",
      }),
      command(waited)({
        type: PacketType.EXEC_END,
        exit_code: 0,
        completion: "exited",
        session_id: null,
        wall_time_seconds: 40,
        truncated: false,
        output: "step 1\nstep 2\n",
        error: null,
      }),
      command(waited)(sectionEnd),
      at(waited)({
        type: PacketType.CODE_MODE_DELTA,
        stdout: "",
        status: "completed",
        cell_id: 1,
        observation: 1,
      }),
      at(waited)(sectionEnd),
      ...answer(2),
    ])
  );
  try {
    await screen.findByText("Done.");
    await expandTimeline();
    expect(screen.getByText(/step 1\s+step 2/)).toBeInTheDocument();
  } finally {
    view.unmount();
  }
});

test("a session that Ctrl-C ended shows as canceled with its output", async () => {
  const command = at({ turn_index: 0, tab_index: 0 });
  const interrupt = at({ turn_index: 1, tab_index: 0 });
  const view = render(
    renderMessage([
      command({
        type: PacketType.EXEC_COMMAND_START,
        cmd: "sleep 600",
        workdir: null,
      }),
      command({
        type: PacketType.EXEC_END,
        exit_code: null,
        completion: null,
        session_id: "4",
        wall_time_seconds: 0.3,
        truncated: false,
        output: "waiting\n",
        error: null,
      }),
      command(sectionEnd),
      interrupt({
        type: PacketType.WRITE_STDIN_START,
        session_id: "4",
        chars: "\u0003",
      }),
      interrupt({
        type: PacketType.EXEC_END,
        exit_code: null,
        completion: "canceled",
        session_id: null,
        wall_time_seconds: 0.2,
        truncated: false,
        output: "tick\n",
        error: null,
      }),
      interrupt(sectionEnd),
      ...answer(2),
    ])
  );
  try {
    await expandTimeline();
    expect(screen.getAllByText("Canceled").length).toBeGreaterThan(0);
    expect(screen.getByText("tick")).toBeInTheDocument();
    expect(
      screen.queryByText("Sent input to session 4")
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Stopped")).not.toBeInTheDocument();
  } finally {
    view.unmount();
  }
});

test("a call the user stopped shows as stopped, not as a result", async () => {
  const command = at({ turn_index: 0, tab_index: 0 });
  const patch = at({ turn_index: 1, tab_index: 0 });
  const view = render(
    renderMessage([
      command({
        type: PacketType.EXEC_COMMAND_START,
        cmd: "sleep 600",
        workdir: null,
      }),
      command({ type: PacketType.EXEC_OUTPUT_DELTA, text: "waiting\n" }),
      command(sectionEnd),
      patch({
        type: PacketType.APPLY_PATCH_START,
        patch: PATCH,
        tool_name: "apply_patch",
      }),
      patch(sectionEnd),
      at({ turn_index: 2, tab_index: 0 })({
        type: PacketType.STOP,
        stop_reason: StopReason.USER_CANCELLED,
      }),
    ])
  );
  try {
    await openRun();
    // Both calls show as stopped.
    expect(await screen.findAllByText("Stopped")).toHaveLength(2);
    expect(screen.getByText("waiting")).toBeInTheDocument();
    expect(screen.queryByText("Ran command")).not.toBeInTheDocument();
    expect(screen.queryByText("No output")).not.toBeInTheDocument();
    expect(screen.queryByText(/Edited/)).not.toBeInTheDocument();
  } finally {
    view.unmount();
  }
});

test("a code mode call that its cell's end cut off shows as stopped", async () => {
  const cell = { turn_index: 0, tab_index: 0 };
  const program = at(cell);
  const command = at({ ...cell, sub_turn_index: 0 });
  const cellPackets = [
    program({ type: PacketType.CODE_MODE_START, code: "await run()" }),
    command({
      type: PacketType.EXEC_COMMAND_START,
      cmd: "sleep 600",
      workdir: null,
    }),
    command({ type: PacketType.EXEC_OUTPUT_DELTA, text: "waiting\n" }),
    // The cell timed out: the nested call gets no end packet.
    program({
      type: PacketType.CODE_MODE_DELTA,
      stdout: "",
      status: "timed_out",
      cell_id: 1,
      observation: 0,
    }),
    program(sectionEnd),
  ];
  const view = render(renderMessage(cellPackets));
  try {
    // Stopped as soon as the cell ends, while the turn goes on
    await openRun();
    expect(await screen.findByText("Stopped")).toBeInTheDocument();
    expect(screen.getByText("waiting")).toBeInTheDocument();
    expect(screen.queryByText("Command failed")).not.toBeInTheDocument();
    expect(screen.queryByText("Ran command")).not.toBeInTheDocument();
  } finally {
    view.unmount();
  }
});

test("published files show in the timeline and as download cards after the answer", async () => {
  const first = at({ turn_index: 0, tab_index: 0 });
  const again = at({ turn_index: 1, tab_index: 0 });
  const failed = at({ turn_index: 2, tab_index: 0 });
  const report = (file_id: string, title: string | null, version: number) => ({
    file_id,
    name: "report.csv",
    title,
    path: "/home/onyx/workspaces/abc/out/report.csv",
    display_path: "out/report.csv",
    size: 2048,
    mime_type: "text/csv",
    artifact_id: "artifact-report",
    version,
    thumbnail_file_id: null,
  });
  const view = render(
    renderMessage([
      first({
        type: PacketType.PUBLISH_FILES_START,
        files: [{ path: "out/report.csv", title: "Q3 report" }],
        description: "The quarterly numbers",
      }),
      first({
        type: PacketType.PUBLISH_FILES_END,
        // The card shows the title without its bidi controls.
        files: [report("file-1", "\u202EQ3 report", 1)],
        error: null,
      }),
      first(sectionEnd),
      // A blank title shows the file's name
      again({
        type: PacketType.PUBLISH_FILES_START,
        files: [{ path: "out/report.csv", title: "  " }],
        description: null,
      }),
      again({
        type: PacketType.PUBLISH_FILES_END,
        files: [report("file-2", "  ", 2)],
        error: null,
      }),
      again(sectionEnd),
      failed({
        type: PacketType.PUBLISH_FILES_START,
        files: [{ path: "missing.pdf", title: null }],
        description: null,
      }),
      failed({
        type: PacketType.PUBLISH_FILES_END,
        files: [],
        error: "missing.pdf is not a file",
      }),
      failed(sectionEnd),
      ...answer(3),
    ])
  );
  try {
    const cards = await screen.findAllByRole("button", {
      name: "Preview report.csv",
    });
    expect(cards).toHaveLength(2);
    expect(within(cards[0]!).getByText("Q3 report")).toBeInTheDocument();
    expect(within(cards[1]!).getByText("report.csv")).toBeInTheDocument();
    expect(screen.getAllByText(/^CSV · /)).toHaveLength(2);
    expect(
      screen
        .getAllByRole("link", { name: "Download" })
        .map((link) => link.getAttribute("href"))
    ).toEqual(["/api/chat/file/file-1", "/api/chat/file/file-2"]);

    await expandTimeline();
    expect(screen.getAllByText("Published 1 file")).toHaveLength(2);
    expect(screen.getByText("The quarterly numbers")).toBeInTheDocument();
    // The second call's row and its card
    expect(screen.getAllByText("report.csv")).toHaveLength(2);
    expect(
      screen.getAllByText("/home/onyx/workspaces/abc/out/report.csv")
    ).toHaveLength(2);
    expect(screen.getByText("Publish failed")).toBeInTheDocument();
    expect(screen.getByText("missing.pdf is not a file")).toBeInTheDocument();
    expect(screen.getByText("missing.pdf")).toBeInTheDocument();
  } finally {
    view.unmount();
  }
});

test("a publish_files call with invalid arguments still shows its step and error", async () => {
  const call = at({ turn_index: 0, tab_index: 0 });
  const view = render(
    renderMessage([
      call({
        type: PacketType.PUBLISH_FILES_START,
        files: [],
        description: null,
      }),
      call({
        type: PacketType.PUBLISH_FILES_END,
        files: [],
        error: "files: field required",
      }),
      call(sectionEnd),
      ...answer(1),
    ])
  );
  try {
    await expandTimeline();
    expect(screen.getByText("Publish failed")).toBeInTheDocument();
    expect(screen.getByText("files: field required")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Preview / })
    ).not.toBeInTheDocument();
  } finally {
    view.unmount();
  }
});
