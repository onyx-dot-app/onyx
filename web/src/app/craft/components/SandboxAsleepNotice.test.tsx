/**
 * @jest-environment jsdom
 */
import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@tests/setup/test-utils";
import SandboxAsleepNotice from "@/app/craft/components/SandboxAsleepNotice";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import * as api from "@/app/craft/services/apiServices";
import { ApiSandboxResponse } from "@/app/craft/types/streamingTypes";

jest.mock("@/app/craft/services/apiServices");

const mockedApi = api as jest.Mocked<typeof api>;

const SESSION_A = "11111111-1111-1111-1111-111111111111";
const SESSION_B = "22222222-2222-2222-2222-222222222222";
const TITLE = "Your sandbox fell asleep";

function sandbox(
  overrides: Partial<ApiSandboxResponse> = {}
): ApiSandboxResponse {
  return {
    id: "sb1",
    status: "sleeping",
    container_id: null,
    created_at: "2026-07-01T00:00:00.000Z",
    last_heartbeat: "2026-07-01T00:00:00.000Z",
    nextjs_port: null,
    ...overrides,
  };
}

function seedSession(
  sessionId: string,
  sandboxState: ApiSandboxResponse
): void {
  useBuildSessionStore.getState().createSession(sessionId, {
    status: "running",
    sandbox: sandboxState,
  });
  useBuildSessionStore.getState().setCurrentSession(sessionId);
}

describe("SandboxAsleepNotice", () => {
  let loadSession: jest.Mock;

  beforeEach(() => {
    jest.clearAllMocks();
    loadSession = jest.fn();
    useBuildSessionStore.setState({
      sessions: new Map(),
      currentSessionId: null,
      loadSession,
    } as never);
    mockedApi.fetchSandboxStatus.mockResolvedValue({ status: "running" });
  });

  it("renders nothing when the sandbox is running", async () => {
    seedSession(SESSION_A, sandbox({ status: "running" }));
    render(<SandboxAsleepNotice />);

    await waitFor(() => {
      expect(mockedApi.fetchSandboxStatus).toHaveBeenCalled();
    });

    expect(screen.queryByText(TITLE)).toBeNull();
  });

  it("shows the modal when the sandbox is sleeping", () => {
    seedSession(SESSION_A, sandbox());
    render(<SandboxAsleepNotice />);

    expect(screen.getByText(TITLE)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Wake sandbox" })
    ).toBeInTheDocument();
  });

  it("hides the modal on dismiss without waking", () => {
    seedSession(SESSION_A, sandbox());
    render(<SandboxAsleepNotice />);

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(screen.queryByText(TITLE)).toBeNull();
    expect(loadSession).not.toHaveBeenCalled();
  });

  it("wakes the sandbox and hides the modal on wake click", () => {
    seedSession(SESSION_A, sandbox());
    render(<SandboxAsleepNotice />);

    fireEvent.click(screen.getByRole("button", { name: "Wake sandbox" }));

    expect(loadSession).toHaveBeenCalledTimes(1);
    expect(loadSession).toHaveBeenCalledWith(SESSION_A, { force: true });
    expect(screen.queryByText(TITLE)).toBeNull();
  });

  it("resets the dismissed state on session switch", () => {
    seedSession(SESSION_A, sandbox());
    render(<SandboxAsleepNotice />);

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText(TITLE)).toBeNull();

    act(() => {
      seedSession(SESSION_B, sandbox());
    });

    expect(screen.getByText(TITLE)).toBeInTheDocument();
  });

  it("dismisses on backdrop click", () => {
    seedSession(SESSION_A, sandbox());
    const { container } = render(<SandboxAsleepNotice />);

    const backdrop = container.firstElementChild?.firstElementChild;
    expect(backdrop).not.toBeNull();
    fireEvent.click(backdrop as Element);

    expect(screen.queryByText(TITLE)).toBeNull();
    expect(loadSession).not.toHaveBeenCalled();
  });
});
