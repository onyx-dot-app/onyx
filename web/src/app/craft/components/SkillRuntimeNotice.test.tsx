/**
 * @jest-environment jsdom
 */
import React from "react";
import { act, fireEvent, render, screen } from "@tests/setup/test-utils";
import SkillRuntimeNotice from "@/app/craft/components/SkillRuntimeNotice";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import type { SkillLimitNotice } from "@/lib/skills/limits";

const SESSION_ID = "11111111-1111-1111-1111-111111111111";
const MB = 1024 * 1024;

function notice(
  skills: SkillLimitNotice["skills"] = [
    {
      plugin_id: "plugin-a",
      name: "design-assets",
      bytes: 600 * MB,
      files: 40,
      reason: "bytes",
    },
    {
      plugin_id: "plugin-b",
      name: "many-files",
      bytes: 12 * MB,
      files: 9000,
      reason: "files",
    },
  ]
): SkillLimitNotice {
  return { skills, max_bytes: 900 * MB, max_files: 10_000 };
}

function setSession(
  updates: Partial<{
    skillOmissions: SkillLimitNotice | null;
    skillsStale: boolean;
  }>
) {
  act(() => {
    useBuildSessionStore.getState().updateSessionData(SESSION_ID, updates);
  });
}

function renderNotice() {
  return render(<SkillRuntimeNotice sessionId={SESSION_ID} />);
}

describe("SkillRuntimeNotice", () => {
  beforeEach(() => {
    useBuildSessionStore.setState({ sessions: new Map() } as never);
    useBuildSessionStore.getState().createSession(SESSION_ID, {});
  });

  it("names each skill, the limit and the actions", () => {
    setSession({ skillOmissions: notice() });
    renderNotice();

    expect(screen.getByText("2 skills did not load")).toBeInTheDocument();
    expect(
      screen.getByText(
        "This session cannot use design-assets and many-files. Your skills must fit in 900 MB and 10,000 files. Turn off skills you do not need to make room."
      )
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Manage skills" })).toHaveAttribute(
      "href",
      "/craft/v1/skills"
    );
  });

  it("shows nothing when every skill loaded", () => {
    setSession({ skillOmissions: null });
    renderNotice();

    expect(screen.queryByText(/did not load/)).not.toBeInTheDocument();
  });

  it("stays dismissed for the same skills and shows a new list", () => {
    setSession({ skillOmissions: notice() });
    renderNotice();

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    setSession({ skillOmissions: notice() });
    expect(screen.queryByText(/did not load/)).not.toBeInTheDocument();

    setSession({ skillOmissions: notice(notice().skills.slice(0, 1)) });
    expect(screen.getByText("1 skill did not load")).toBeInTheDocument();
  });

  it("waits while the session's skills are stale", () => {
    setSession({ skillOmissions: notice(), skillsStale: true });
    renderNotice();
    expect(screen.queryByText(/did not load/)).not.toBeInTheDocument();

    setSession({ skillsStale: false });
    expect(screen.getByText("2 skills did not load")).toBeInTheDocument();
  });
});
