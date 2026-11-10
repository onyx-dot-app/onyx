/**
 * @jest-environment jsdom
 */
import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  within,
} from "@tests/setup/test-utils";
import { ToastProvider, toast } from "@opal/layouts";
import SkillRuntimeNotice from "@/app/craft/components/SkillRuntimeNotice";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import type {
  ApiSkillRuntimeNotice,
  ApiSkillRuntimeOmission,
} from "@/app/craft/types/streamingTypes";

const SESSION_ID = "11111111-1111-1111-1111-111111111111";
const OTHER_SESSION_ID = "22222222-2222-2222-2222-222222222222";
const MIB = 1024 * 1024;

function omission(
  name: string,
  overrides: Partial<ApiSkillRuntimeOmission> = {}
): ApiSkillRuntimeOmission {
  return {
    skill_id: `id-${name}`,
    name,
    charged_bytes: 950 * MIB,
    file_count: 3,
    failed_limit: "bytes",
    ...overrides,
  };
}

function notice(
  ...omissions: ApiSkillRuntimeOmission[]
): ApiSkillRuntimeNotice {
  return {
    max_bytes: 900 * MIB,
    max_files: 10_000,
    max_directories: 10_000,
    max_path_bytes: 4021,
    max_path_component_bytes: 255,
    omissions,
  };
}

function setNotice(
  sessionId: string,
  value: ApiSkillRuntimeNotice | null
): void {
  act(() => {
    useBuildSessionStore.getState().updateSessionData(sessionId, {
      skillsStale: false,
      skillRuntimeNotice: value,
    });
  });
}

function renderNotice(sessionId: string = SESSION_ID) {
  return render(
    <ToastProvider>
      <SkillRuntimeNotice sessionId={sessionId} />
    </ToastProvider>
  );
}

/** The visible toast titles; the alert repeats them for screen readers. */
function toasts(): string[] {
  return Array.from(
    document.querySelectorAll("[data-opal-content-title]"),
    (title) => title.textContent ?? ""
  );
}

describe("SkillRuntimeNotice", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    useBuildSessionStore.setState({ sessions: new Map() } as never);
    useBuildSessionStore.getState().createSession(SESSION_ID);
    useBuildSessionStore.getState().createSession(OTHER_SESSION_ID);
  });

  afterEach(() => {
    act(() => toast.clearAll());
    jest.useRealTimers();
  });

  // ===== Content =====

  it("lists each Skill with its size, the limits and the actions", () => {
    setNotice(
      SESSION_ID,
      notice(
        omission("big-data"),
        omission("many-files", {
          charged_bytes: 40 * MIB,
          file_count: 6_000,
          failed_limit: "files",
        })
      )
    );
    renderNotice();

    expect(toasts()).toEqual(["2 skills did not load"]);
    const description =
      "Your skills must fit in 900 MB and 10,000 files. Individual file, folder, and path limits also apply. These skills exceed a delivery limit, so the agent cannot use them in this session.";
    // Shown under the title and announced by the alert.
    expect(screen.getAllByText(description)).toHaveLength(2);
    const list = screen.getByRole("list");
    const region = screen.getByRole("region", {
      name: "Skills that did not load",
    });
    expect(region).toHaveAttribute("tabindex", "0");
    expect(region).toHaveClass("max-h-[min(20rem,25dvh)]", "overflow-y-auto");
    expect(
      within(list)
        .getAllByRole("listitem")
        .map((item) => item.textContent)
    ).toEqual(["big-data: 950 MB", "many-files: 40 MB, 6,000 files"]);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "2 skills did not load"
    );
    expect(screen.getByRole("alert")).toHaveTextContent(description);
    expect(screen.getByRole("link", { name: "Manage skills" })).toHaveAttribute(
      "href",
      "/craft/v1/skills"
    );
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeEnabled();
  });

  it("stays until dismissed", () => {
    setNotice(SESSION_ID, notice(omission("big-data")));
    renderNotice();

    act(() => jest.advanceTimersByTime(60_000));
    expect(toasts()).toEqual(["1 skill did not load"]);

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    act(() => jest.advanceTimersByTime(1_000));
    expect(toasts()).toHaveLength(0);
  });

  // ===== Repeat and new states =====

  it("does not raise a dismissed notice again on refetch or remount", () => {
    setNotice(SESSION_ID, notice(omission("big-data")));
    const { unmount } = renderNotice();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    act(() => jest.advanceTimersByTime(1_000));

    // A routine poll returns an equal but new object.
    setNotice(SESSION_ID, notice(omission("big-data")));
    unmount();
    renderNotice();

    expect(toasts()).toHaveLength(0);
  });

  it("raises a new omission state after a dismissal", () => {
    setNotice(SESSION_ID, notice(omission("big-data")));
    renderNotice();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    act(() => jest.advanceTimersByTime(1_000));

    setNotice(SESSION_ID, notice(omission("big-data"), omission("new-large")));

    expect(toasts()).toEqual(["2 skills did not load"]);
    expect(toasts()).toHaveLength(1);
  });

  it("clears the toast when omissions end and raises a later recurrence", () => {
    setNotice(SESSION_ID, notice(omission("big-data")));
    renderNotice();

    setNotice(SESSION_ID, null);
    act(() => jest.advanceTimersByTime(1_000));
    expect(toasts()).toHaveLength(0);
    expect(
      useBuildSessionStore.getState().sessions.get(SESSION_ID)
        ?.skillRuntimeNoticeDismissed
    ).toBe(false);

    setNotice(SESSION_ID, notice(omission("big-data")));
    expect(toasts()).toEqual(["1 skill did not load"]);
  });

  it("removes its global toast on unmount and restores an undismissed notice", () => {
    setNotice(SESSION_ID, notice(omission("big-data")));
    const view = renderNotice();
    view.rerender(
      <ToastProvider>
        <main>Skills page</main>
      </ToastProvider>
    );
    act(() => jest.advanceTimersByTime(1_000));
    expect(toasts()).toEqual([]);
    view.rerender(
      <ToastProvider>
        <SkillRuntimeNotice sessionId={SESSION_ID} />
      </ToastProvider>
    );
    expect(toasts()).toEqual(["1 skill did not load"]);
  });

  it("restores A after visiting B without treating display as dismissal", () => {
    setNotice(SESSION_ID, notice(omission("big-data")));
    const view = renderNotice();
    view.rerender(
      <ToastProvider>
        <SkillRuntimeNotice sessionId={OTHER_SESSION_ID} />
      </ToastProvider>
    );
    act(() => jest.advanceTimersByTime(1_000));
    expect(toasts()).toEqual([]);
    view.rerender(
      <ToastProvider>
        <SkillRuntimeNotice sessionId={SESSION_ID} />
      </ToastProvider>
    );
    expect(toasts()).toEqual(["1 skill did not load"]);
  });

  it("defers sandbox omissions until the session loads the new skills", () => {
    setNotice(SESSION_ID, notice(omission("big-data")));
    act(() =>
      useBuildSessionStore
        .getState()
        .updateSessionData(SESSION_ID, { skillsStale: true })
    );
    renderNotice();
    expect(toasts()).toEqual([]);
    act(() =>
      useBuildSessionStore
        .getState()
        .updateSessionData(SESSION_ID, { skillsStale: false })
    );
    expect(toasts()).toEqual(["1 skill did not load"]);
  });

  it("resets dismissal when a background refresh clears and restores omissions", () => {
    setNotice(SESSION_ID, notice(omission("big-data")));
    const view = renderNotice();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    view.unmount();
    act(() => jest.advanceTimersByTime(1_000));
    setNotice(SESSION_ID, null);
    setNotice(SESSION_ID, notice(omission("big-data")));
    renderNotice();
    expect(toasts()).toEqual(["1 skill did not load"]);
  });

  // ===== Session isolation =====

  it("ignores another session's omission state", () => {
    renderNotice();

    setNotice(OTHER_SESSION_ID, notice(omission("big-data")));

    expect(toasts()).toHaveLength(0);
    expect(
      useBuildSessionStore.getState().sessions.get(OTHER_SESSION_ID)
        ?.skillRuntimeNoticeDismissed
    ).toBe(false);
  });
});

describe("runtime transport limit descriptions", () => {
  afterEach(() => act(() => toast.clearAll()));

  it("names folder and UTF-8 path limits instead of reporting a byte overflow", () => {
    useBuildSessionStore.getState().createSession(SESSION_ID);
    setNotice(
      SESSION_ID,
      notice(
        omission("deep-folders", { failed_limit: "directories" }),
        omission("long-path", { failed_limit: "paths" })
      )
    );
    renderNotice();
    const list = screen.getByRole("list");
    expect(
      within(list).getByText(/deep-folders:.*10,000 folders/)
    ).toBeVisible();
    expect(
      within(list).getByText(/long-path:.*4,021 UTF-8 bytes/)
    ).toBeVisible();
  });
});
