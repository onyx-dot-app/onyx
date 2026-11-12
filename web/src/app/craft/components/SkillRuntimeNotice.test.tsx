/**
 * @jest-environment jsdom
 */
import React from "react";
import { act, fireEvent, render, screen } from "@tests/setup/test-utils";
import { ToastProvider, toast } from "@opal/layouts";
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
  return render(
    <ToastProvider>
      <SkillRuntimeNotice sessionId={SESSION_ID} />
    </ToastProvider>
  );
}

describe("SkillRuntimeNotice", () => {
  let errorSpy: jest.SpyInstance;

  beforeEach(() => {
    toast.clearAll();
    errorSpy = jest.spyOn(toast, "error");
    useBuildSessionStore.setState({ sessions: new Map() } as never);
    useBuildSessionStore.getState().createSession(SESSION_ID, {});
  });

  afterEach(() => {
    errorSpy.mockRestore();
    toast.clearAll();
  });

  it("lists each skill with its size, the limit and the actions", () => {
    setSession({ skillOmissions: notice() });
    renderNotice();

    expect(screen.getByText("2 skills did not load")).toBeInTheDocument();
    expect(
      screen.getByText(/Your skills must fit in 900 MB and 10,000 files\./)
    ).toBeInTheDocument();
    expect(screen.getByText("design-assets: 600 MB")).toBeInTheDocument();
    expect(
      screen.getByText("many-files: 12 MB, 9,000 files")
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Manage skills" })).toHaveAttribute(
      "href",
      "/craft/v1/skills"
    );
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeEnabled();
  });

  it("shows nothing when every skill loaded", () => {
    setSession({ skillOmissions: null });
    renderNotice();

    expect(errorSpy).not.toHaveBeenCalled();
    expect(screen.queryByText(/did not load/)).not.toBeInTheDocument();
  });

  it("raises the toast once for the same omission set", () => {
    setSession({ skillOmissions: notice() });
    renderNotice();
    // A later session read returns an equal set in a new object.
    setSession({ skillOmissions: notice() });
    setSession({ skillOmissions: notice() });

    expect(errorSpy).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText("2 skills did not load")).toHaveLength(1);
  });

  it("stays dismissed until the omission set changes", () => {
    setSession({ skillOmissions: notice() });
    renderNotice();

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    setSession({ skillOmissions: notice() });
    expect(errorSpy).toHaveBeenCalledTimes(1);

    setSession({ skillOmissions: notice(notice().skills.slice(0, 1)) });
    expect(errorSpy).toHaveBeenCalledTimes(2);
    expect(errorSpy).toHaveBeenLastCalledWith(
      "1 skill did not load",
      expect.anything()
    );
  });

  it("waits while the session's skills are stale", () => {
    setSession({ skillOmissions: notice(), skillsStale: true });
    renderNotice();
    expect(errorSpy).not.toHaveBeenCalled();

    setSession({ skillsStale: false });
    expect(errorSpy).toHaveBeenCalledTimes(1);
  });
});
