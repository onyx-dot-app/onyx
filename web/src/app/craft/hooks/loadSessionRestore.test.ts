import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import * as api from "@/app/craft/services/apiServices";

jest.mock("@/app/craft/services/apiServices");

const mockedApi = api as jest.Mocked<typeof api>;

const SESSION_ID = "11111111-1111-1111-1111-111111111111";

// Minimal DetailedSessionResponse shapes — loadSession only reads status,
// session_loaded_in_sandbox, and sandbox.{status,nextjs_port}.
function sleepingSession(): unknown {
  return {
    id: SESSION_ID,
    status: "idle",
    session_loaded_in_sandbox: false,
    sandbox: { id: "sb1", status: "sleeping", nextjs_port: null },
  };
}

function runningSession(): unknown {
  return {
    id: SESSION_ID,
    status: "active",
    session_loaded_in_sandbox: true,
    sandbox: { id: "sb1", status: "running", nextjs_port: null },
  };
}

describe("loadSession restore status", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useBuildSessionStore.setState({
      sessions: new Map(),
      currentSessionId: null,
    } as never);
    mockedApi.fetchMessages.mockResolvedValue([] as never);
    mockedApi.fetchArtifacts.mockResolvedValue([] as never);
  });

  it("keeps the sandbox running when the post-restore artifact fetch fails", async () => {
    mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
    mockedApi.restoreSession.mockResolvedValue(runningSession() as never);
    // Artifacts list the sandbox via opencode-serve and can fail right after
    // the pod comes up — this must NOT flip the sandbox to "failed".
    mockedApi.fetchArtifacts.mockRejectedValue(new Error("opencode not ready"));

    await useBuildSessionStore.getState().loadSession(SESSION_ID);

    const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    expect(session?.sandbox?.status).toBe("running");
  });

  it("marks the sandbox failed when restore itself fails", async () => {
    mockedApi.fetchSession.mockResolvedValue(sleepingSession() as never);
    mockedApi.restoreSession.mockRejectedValue(new Error("restore boom"));

    await useBuildSessionStore.getState().loadSession(SESSION_ID);

    const session = useBuildSessionStore.getState().sessions.get(SESSION_ID);
    expect(session?.sandbox?.status).toBe("failed");
  });
});
