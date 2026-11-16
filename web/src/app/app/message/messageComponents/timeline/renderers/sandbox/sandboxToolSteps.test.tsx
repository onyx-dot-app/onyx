import { act, render, screen } from "@tests/setup/test-utils";
import { Message } from "@/app/app/types";
import { upsertMessages } from "@/app/app/services/messageTree";
import {
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

async function expandTimeline() {
  await screen.findByText("Done.");
  await act(async () => {
    screen.getByRole("button", { name: "Expand timeline" }).click();
  });
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

test("a patch lists the files it changed, and a failed patch says why", async () => {
  const applied = at({ turn_index: 0, tab_index: 0 });
  const rejected = at({ turn_index: 1, tab_index: 0 });
  const view = render(
    renderMessage([
      applied({ type: PacketType.APPLY_PATCH_START, patch: PATCH }),
      applied({
        type: PacketType.APPLY_PATCH_END,
        files: [
          { path: "new.py", change: "add", move_path: null },
          { path: "old.py", change: "update", move_path: "moved.py" },
        ],
        error: null,
      }),
      applied(sectionEnd),
      rejected({ type: PacketType.APPLY_PATCH_START, patch: PATCH }),
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
    expect(screen.getByText("old.py → moved.py")).toBeInTheDocument();
    // The card lays out only the head of each patch.
    expect(screen.getAllByText(/\+print\('hi'\)/)).toHaveLength(2);
    expect(screen.queryByText(/\+a = 2/)).not.toBeInTheDocument();
    expect(screen.getByText("Patch failed")).toBeInTheDocument();
    expect(
      screen.getByText("Failed to find expected lines in old.py")
    ).toBeInTheDocument();
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
      applied({ type: PacketType.APPLY_PATCH_START, patch }),
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
      patch({ type: PacketType.APPLY_PATCH_START, patch: PATCH }),
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
    expect(screen.getByText("2 steps")).toBeInTheDocument();
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
    expect(screen.getByText("1 step")).toBeInTheDocument();
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
      patch({ type: PacketType.APPLY_PATCH_START, patch: PATCH }),
      patch(sectionEnd),
      at({ turn_index: 2, tab_index: 0 })({
        type: PacketType.STOP,
        stop_reason: StopReason.USER_CANCELLED,
      }),
    ])
  );
  try {
    await act(async () => {
      (await screen.findByRole("button", { name: "Expand timeline" })).click();
    });
    // Both calls, and the timeline's own stopped step
    expect(await screen.findAllByText("Stopped")).toHaveLength(3);
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
    await act(async () => {
      (await screen.findByRole("button", { name: "Expand timeline" })).click();
    });
    expect(await screen.findByText("Stopped")).toBeInTheDocument();
    expect(screen.getByText("waiting")).toBeInTheDocument();
    expect(screen.queryByText("Command failed")).not.toBeInTheDocument();
    expect(screen.queryByText("Ran command")).not.toBeInTheDocument();
  } finally {
    view.unmount();
  }
});
