/**
 * @jest-environment jsdom
 */
import React from "react";
import { fireEvent, render, screen, waitFor } from "@tests/setup/test-utils";
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
      skill_omissions: null,
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

  it("replaces the skills that did not load with the reload's result", async () => {
    useBuildSessionStore.getState().updateSessionData(SESSION_ID, {
      skillOmissions: {
        skills: [
          {
            plugin_id: "p1",
            name: "old-skill",
            bytes: 1,
            files: 1,
            reason: "bytes",
          },
        ],
        max_bytes: 10,
        max_files: 10,
      },
    });
    render(<SkillsStaleNotice sessionId={SESSION_ID} turnActive={false} />);

    fireEvent.click(screen.getByRole("button", { name: "Reload" }));

    await waitFor(() =>
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)?.skillOmissions
      ).toBeNull()
    );
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
