/**
 * @jest-environment jsdom
 */
import React from "react";
import {
  act,
  deferred,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@tests/setup/test-utils";
import SkillsStaleNotice from "@/app/craft/components/SkillsStaleNotice";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import * as api from "@/app/craft/services/apiServices";

jest.mock("@/app/craft/services/apiServices");

const SESSION_ID = "11111111-1111-1111-1111-111111111111";

describe("SkillsStaleNotice", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useBuildSessionStore.setState({ sessions: new Map() } as never);
    useBuildSessionStore.getState().createSession(SESSION_ID, {
      skillsStale: true,
    });
    jest.mocked(api.reloadSessionSkills).mockResolvedValue({
      skills_stale: false,
      skill_runtime_notice: null,
    });
  });

  it("reloads only this session and clears its stale state", async () => {
    render(<SkillsStaleNotice sessionId={SESSION_ID} turnActive={false} />);

    fireEvent.click(screen.getByRole("button", { name: "Reload" }));

    await waitFor(() => {
      expect(api.reloadSessionSkills).toHaveBeenCalledWith(SESSION_ID);
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)?.skillsStale
      ).toBe(false);
    });
  });

  it.each(["before", "during"])(
    "keeps reload results when a refresh starts %s reload",
    async (order) => {
      const pending =
        deferred<Awaited<ReturnType<typeof api.reloadSessionSkills>>>();
      const read = deferred<Awaited<ReturnType<typeof api.fetchSession>>>();
      jest.mocked(api.reloadSessionSkills).mockReturnValueOnce(pending.promise);
      jest.mocked(api.fetchSession).mockReturnValueOnce(read.promise);
      const store = useBuildSessionStore.getState();
      let refresh = Promise.resolve();
      render(<SkillsStaleNotice sessionId={SESSION_ID} turnActive={false} />);
      if (order === "before") refresh = store.refreshSessionSkills(SESSION_ID);
      fireEvent.click(screen.getByRole("button", { name: "Reload" }));
      if (order === "during") refresh = store.refreshSessionSkills(SESSION_ID);
      await act(async () => {
        read.resolve({
          id: SESSION_ID,
          user_id: null,
          name: null,
          status: "active",
          created_at: "",
          last_activity_at: "",
          nextjs_port: null,
          sandbox: null,
          artifacts: [],
          sharing_scope: "private",
          origin: "INTERACTIVE",
          agent_provider: null,
          agent_model: null,
          skills_stale: true,
          skill_runtime_notice: null,
          session_loaded_in_sandbox: true,
        });
        await refresh;
      });
      await act(async () =>
        pending.resolve({ skills_stale: false, skill_runtime_notice: null })
      );
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)
      ).toMatchObject({ skillsStale: false, skillsReloadRevision: null });
    }
  );

  it.each([
    "navigation",
    "unmount",
    "recreated session",
    "newer turn",
    "newer state",
  ])("ignores a reload response after %s", async (change) => {
    const pending =
      deferred<Awaited<ReturnType<typeof api.reloadSessionSkills>>>();
    jest.mocked(api.reloadSessionSkills).mockReturnValueOnce(pending.promise);
    const view = render(
      <SkillsStaleNotice sessionId={SESSION_ID} turnActive={false} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Reload" }));
    act(() => {
      const store = useBuildSessionStore.getState();
      if (change === "navigation") {
        store.createSession("other", { skillsStale: true });
        view.rerender(
          <SkillsStaleNotice sessionId="other" turnActive={false} />
        );
      } else if (change === "unmount") view.unmount();
      else if (change === "recreated session")
        store.createSession(SESSION_ID, { skillsStale: true });
      else
        store.updateSessionData(
          SESSION_ID,
          change === "newer turn"
            ? { turnGeneration: 1 }
            : { skillsStale: true }
        );
    });
    await act(async () =>
      pending.resolve({ skills_stale: false, skill_runtime_notice: null })
    );
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)?.skillsStale
    ).toBe(true);
    if (change === "navigation")
      expect(screen.getByRole("button", { name: "Reload" })).toBeEnabled();
  });

  it("reveals retained stale state after an active turn stops", () => {
    const { rerender } = render(
      <SkillsStaleNotice sessionId={SESSION_ID} turnActive />
    );

    expect(
      screen.queryByRole("button", { name: "Reload" })
    ).not.toBeInTheDocument();

    rerender(<SkillsStaleNotice sessionId={SESSION_ID} turnActive={false} />);

    expect(screen.getByRole("button", { name: "Reload" })).toBeEnabled();
  });
});
