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
    });
  });

  it("reloads only this session and clears its stale state", async () => {
    render(<SkillsStaleNotice sessionId={SESSION_ID} turnActive={false} />);

    fireEvent.click(screen.getByRole("button", { name: "Reload skills" }));

    await waitFor(() => {
      expect(api.reloadSessionSkills).toHaveBeenCalledWith(SESSION_ID);
      expect(
        useBuildSessionStore.getState().sessions.get(SESSION_ID)?.skillsStale
      ).toBe(false);
    });
  });

  it("disables reload while a turn is active", () => {
    render(<SkillsStaleNotice sessionId={SESSION_ID} turnActive />);

    expect(
      screen.getByRole("button", { name: "Reload skills" })
    ).toBeDisabled();
  });
});
