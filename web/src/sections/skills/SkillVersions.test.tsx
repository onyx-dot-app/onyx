import {
  act,
  deferred,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { unstable_serialize } from "swr/infinite";
import { Button } from "@opal/components";
import SkillVersions from "@/sections/skills/SkillVersions";
import { customFixture } from "@/lib/skills/__fixtures__/picker";
import type {
  SkillVersion,
  SkillEditableDetail,
  SkillsList,
  SkillPreview,
} from "@/lib/skills/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";

const skill = customFixture({
  user_permission: "OWNER",
  current_version_number: 3,
});
const versions: SkillVersion[] = [
  {
    id: "v3",
    version_number: 3,
    created_at: "2026-11-08T12:00:00Z",
    created_by: { id: "owner", email: "owner@example.com" },
    is_current: true,
    has_bundle: true,
    marketplace_revision: null,
  },
  {
    id: "v2",
    version_number: 2,
    created_at: "2026-11-07T12:00:00Z",
    created_by: null,
    is_current: false,
    has_bundle: false,
    marketplace_revision: null,
  },
  {
    id: "v1",
    version_number: 1,
    created_at: "2026-11-06T12:00:00Z",
    created_by: null,
    is_current: false,
    has_bundle: true,
    marketplace_revision: null,
  },
];
const bundle = {
  name: skill.name,
  description: "Earlier description",
  instructions_markdown: "Earlier instructions",
  files: [{ path: "references/example.md", size: 10 }],
};
const restored: SkillEditableDetail = {
  ...skill,
  ...bundle,
  current_version_number: 4,
};
const fetchMock = jest.fn<
  Promise<Response>,
  [RequestInfo | URL, RequestInit?]
>();
const response = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status });

beforeEach(() => {
  fetchMock.mockReset().mockImplementation(async (url) => {
    if (url === SWR_KEYS.skillVersions(skill.id)) return response(versions);
    if (url === SWR_KEYS.skillVersion(skill.id, "v1")) return response(bundle);
    throw new Error(`Unexpected request: ${url}`);
  });
  global.fetch = fetchMock;
});

function showHistory(overrides: Partial<typeof skill> = {}) {
  const onBusyChange = jest.fn();
  const onRestored = jest.fn();
  render(
    <SkillVersions
      skill={{ ...skill, ...overrides }}
      onBusyChange={onBusyChange}
      onRestored={onRestored}
    />
  );
  return { onBusyChange, onRestored };
}

test("blocks restore for unsaved editor changes while keeping preview available", async () => {
  const user = setupUser();
  render(
    <SkillVersions
      skill={skill}
      restoreDisabled
      onBusyChange={jest.fn()}
      onRestored={jest.fn()}
    />
  );
  expect(
    await screen.findByRole("button", { name: "Restore version 1" })
  ).toBeDisabled();
  expect(
    screen.getByText(
      "Save or discard your editor changes before restoring a version."
    )
  ).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Preview version 1" }));
  expect(await screen.findByText("Earlier instructions")).toBeVisible();
  expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(
    false
  );
});

test("shows loading, a retryable error and the empty state", async () => {
  const request = deferred<Response>();
  fetchMock.mockReturnValueOnce(request.promise);
  showHistory();
  expect(screen.getByText("Loading versions…")).toBeVisible();
  await act(async () =>
    request.resolve(response({ detail: "Unavailable" }, 503))
  );
  expect(await screen.findByText("Could not load versions.")).toBeVisible();
  fetchMock.mockResolvedValueOnce(response([]));
  await setupUser().click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("No versions yet.")).toBeVisible();
});

test.each([390, 1280])(
  "shows every metadata field and only retained historical restore actions at width %s",
  async (width) => {
    const originalWidth = window.innerWidth;
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: width,
    });
    try {
      showHistory();
      expect(await screen.findByText("Current")).toBeVisible();
      expect(screen.getByText("owner@example.com")).toBeVisible();
      expect(screen.getAllByText("Unknown creator")).toHaveLength(2);
      expect(screen.getByText("Initial version")).toBeVisible();
      expect(screen.getAllByText("Content updated")).toHaveLength(2);
      expect(screen.getByText(/Nov 8, 2026/)).toBeVisible();
      expect(screen.getByText("Files no longer retained")).toBeVisible();
      expect(
        screen.queryByRole("button", { name: "Restore version 3" })
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Preview version 2" })
      ).not.toBeInTheDocument();
      expect(
        screen.getAllByRole("button", { name: /Restore version/ })
      ).toHaveLength(1);
      expect(
        screen.getByRole(width < 768 ? "list" : "table", { name: "Versions" })
      ).toBeVisible();
    } finally {
      Object.defineProperty(window, "innerWidth", {
        configurable: true,
        value: originalWidth,
      });
    }
  }
);

test("previews retained content, retries failed previews and returns focus to history", async () => {
  const user = setupUser();
  showHistory();
  await screen.findByText("Initial version");
  fetchMock.mockResolvedValueOnce(response({ detail: "Unavailable" }, 503));
  await user.click(screen.getByRole("button", { name: "Preview version 1" }));
  expect(await screen.findByText("Could not load this version.")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("Earlier instructions")).toBeVisible();
  expect(screen.getByText("references/example.md")).toBeVisible();
  expect(screen.getByRole("heading", { name: "report-writer" })).toHaveFocus();
  await user.click(screen.getByRole("button", { name: "Back" }));
  expect(screen.getByRole("heading", { name: "Versions" })).toHaveFocus();
});

test("synced history labels the stored revision and offers no restore", async () => {
  fetchMock.mockResolvedValueOnce(
    response(
      versions.map((version) => ({
        ...version,
        marketplace_revision: "abc123",
      }))
    )
  );
  showHistory({
    marketplace: {
      id: "source",
      name: "Source",
      personal: false,
      folder: null,
      follows_access: true,
      can_share: false,
    },
  });
  expect(
    (await screen.findAllByText("Synced revision abc123"))[0]
  ).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /Restore/ })
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Preview version 3" })
  ).toBeVisible();
});

test("confirms restore and preserves errors for retry without calling the parent on failure", async () => {
  const user = setupUser();
  const { onBusyChange, onRestored } = showHistory();
  await user.click(
    await screen.findByRole("button", { name: "Restore version 1" })
  );
  expect(
    screen.getByRole("heading", { name: "Restore version 1?" })
  ).toHaveFocus();
  expect(fetchMock).not.toHaveBeenCalledWith(
    expect.stringContaining("/restore"),
    expect.anything()
  );
  const request = deferred<Response>();
  fetchMock.mockReturnValueOnce(request.promise);
  await user.click(screen.getByRole("button", { name: "Restore" }));
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  expect(onBusyChange).toHaveBeenLastCalledWith(true);
  await act(async () =>
    request.resolve(response({ detail: "Restore denied" }, 403))
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("Restore denied");
  expect(onRestored).not.toHaveBeenCalled();
  expect(onBusyChange).toHaveBeenLastCalledWith(false);
  fetchMock.mockResolvedValueOnce(response(restored));
  await user.click(screen.getByRole("button", { name: "Restore" }));
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Selected version content is now current."
  );
  expect(onRestored).toHaveBeenCalledTimes(1);
});

test("explains a restore the Skill limit refused, with an estimated usage", async () => {
  const user = setupUser();
  const { onRestored } = showHistory();
  await user.click(
    await screen.findByRole("button", { name: "Restore version 1" })
  );
  fetchMock.mockResolvedValueOnce(
    response(
      {
        error_code: "PAYLOAD_TOO_LARGE",
        detail: "This would put your skills at 600.0 MB",
        skill_limit: {
          failed_limit: "bytes",
          affected_user_count: 1,
          usage: {
            bytes: 500 * 1024 * 1024,
            files: 10,
            unknown_skill_count: 1,
            charged_bytes: 600 * 1024 * 1024,
            charged_files: 510,
            max_bytes: 500 * 1024 * 1024,
            max_files: 5000,
          },
        },
      },
      413
    )
  );
  await user.click(screen.getByRole("button", { name: "Restore" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "This change would put your skills at an estimated 600 MB in 510 files. The estimate counts 1 skill not yet measured at the largest allowed size. The limit is 500 MB and 5,000 files."
  );
  expect(onRestored).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "Restore" })).toBeEnabled();
});

function CurrentContent() {
  const { data: detail } = useSWR<SkillEditableDetail>(
    SWR_KEYS.editableSkill(skill.id),
    errorHandlingFetcher
  );
  const { data: preview } = useSWR<SkillPreview>(
    SWR_KEYS.userSkillPreview(skill.id),
    errorHandlingFetcher
  );
  const { data: library } = useSWR<SkillsList>(
    SWR_KEYS.userSkills,
    errorHandlingFetcher
  );
  return (
    <section aria-label="Current content">
      {detail?.instructions_markdown} {preview?.description}{" "}
      {library?.customs[0]?.current_version_number}
    </section>
  );
}

test.each([3, 4])(
  "refreshes history, current details, preview and library after restore (current version %s)",
  async (number) => {
    let didRestore = false;
    const result = { ...restored, current_version_number: number };
    fetchMock.mockImplementation(async (url, init) => {
      if (init?.method === "POST") {
        didRestore = true;
        return response(result);
      }
      if (url === SWR_KEYS.skillVersions(skill.id))
        return response(
          didRestore
            ? [{ ...versions[0], id: "current", version_number: number }]
            : versions
        );
      if (url === SWR_KEYS.userSkills)
        return response({
          builtins: [],
          customs: [didRestore ? result : skill],
        });
      return response(
        didRestore
          ? result
          : { ...skill, instructions_markdown: "Current instructions" }
      );
    });
    render(
      <>
        <SkillVersions
          skill={skill}
          onBusyChange={jest.fn()}
          onRestored={jest.fn()}
        />
        <CurrentContent />
      </>
    );
    const user = setupUser();
    await user.click(
      await screen.findByRole("button", { name: "Restore version 1" })
    );
    await user.click(screen.getByRole("button", { name: "Restore" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Selected version content is now current."
    );
    const current = screen.getByRole("region", { name: "Current content" });
    await waitFor(() =>
      expect(current).toHaveTextContent(
        `Earlier instructions Earlier description ${number}`
      )
    );
    expect(
      within(screen.getByRole("table")).queryByText("Initial version")
    ).not.toBeInTheDocument();
  }
);

test.each([
  { width: 320, count: 55 },
  { width: 1280, count: 55 },
  { width: 320, count: 100 },
  { width: 1280, count: 100 },
])(
  "loads $count versions, retries and restores at width $width",
  async ({ width, count }) => {
    const originalWidth = window.innerWidth;
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: width,
    });
    try {
      const history = Array.from(
        { length: count },
        (_, index): SkillVersion => {
          const number = count - index;
          return {
            id: `v${number}`,
            version_number: number,
            created_at: "2026-11-08T12:00:00Z",
            created_by: null,
            is_current: number === count,
            has_bundle: true,
            marketplace_revision: null,
          };
        }
      );
      let olderFailed = false;
      const olderRequest = deferred<Response>();
      fetchMock.mockImplementation(async (input, init) => {
        const url = new URL(String(input), "http://localhost");
        if (url.pathname === SWR_KEYS.skillVersions(skill.id)) {
          const before = Number(
            url.searchParams.get("before_version") ?? Infinity
          );
          if (before === count - 49 && !olderFailed) {
            olderFailed = true;
            return olderRequest.promise;
          }
          return response(
            history.filter((row) => row.version_number < before).slice(0, 50)
          );
        }
        if (init?.method === "POST") {
          const latest = history[0];
          if (!latest)
            throw new Error("The fixture must have a current version");
          history[0] = { ...latest, is_current: false };
          history.unshift({
            ...latest,
            id: `v${count + 1}`,
            version_number: count + 1,
            is_current: true,
          });
          return response({ ...restored, current_version_number: count + 1 });
        }
        return response(bundle);
      });
      const user = setupUser();
      showHistory();
      expect(
        await screen.findByRole("button", { name: `Preview version ${count}` })
      ).toBeVisible();
      expect(
        screen.queryByRole("button", { name: `Preview version ${count - 50}` })
      ).not.toBeInTheDocument();
      expect(fetchMock).toHaveBeenCalledTimes(1);
      await user.click(
        screen.getByRole("button", { name: "Load older versions" })
      );
      expect(
        screen.getByRole("button", { name: `Preview version ${count}` })
      ).toBeVisible();
      await act(async () =>
        olderRequest.resolve(response({ detail: "Unavailable" }, 503))
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Could not load versions."
      );
      expect(
        screen.getByRole("button", { name: `Preview version ${count}` })
      ).toBeVisible();
      await user.click(screen.getByRole("button", { name: "Retry" }));
      expect(
        await screen.findByRole("button", { name: "Preview version 1" })
      ).toBeVisible();
      await waitFor(() =>
        expect(
          screen.getByText(
            width === 320 ? `Version ${count - 50}` : String(count - 50)
          )
        ).toHaveFocus()
      );
      expect(
        screen.queryByRole("button", { name: "Load older versions" })
      ).not.toBeInTheDocument();
      await user.click(
        screen.getByRole("button", { name: "Restore version 1" })
      );
      await user.click(screen.getByRole("button", { name: "Restore" }));
      expect(
        await screen.findByRole("button", {
          name: `Preview version ${count + 1}`,
        })
      ).toBeVisible();
      expect(
        screen.getAllByRole("button", { name: /^Preview version/ })
      ).toHaveLength(count + 1);
      expect(
        screen.getByRole("button", { name: "Preview version 1" })
      ).toBeVisible();
      expect(screen.getAllByText("Current")).toHaveLength(1);
    } finally {
      Object.defineProperty(window, "innerWidth", {
        configurable: true,
        value: originalWidth,
      });
    }
  }
);

test("a background retry does not move focus after an older page fails", async () => {
  let failOlder = true;
  const history = Array.from(
    { length: 55 },
    (_, index): SkillVersion => ({
      id: `v${55 - index}`,
      version_number: 55 - index,
      created_at: "2026-11-08T12:00:00Z",
      created_by: null,
      is_current: index === 0,
      has_bundle: true,
      marketplace_revision: null,
    })
  );
  fetchMock.mockImplementation(async (input) => {
    const url = new URL(String(input), "http://localhost");
    const before = Number(url.searchParams.get("before_version") ?? Infinity);
    if (before === 6 && failOlder)
      return response({ detail: "Unavailable" }, 503);
    return response(
      history.filter((row) => row.version_number < before).slice(0, 50)
    );
  });
  function RefreshElsewhere() {
    const { mutate } = useSWRConfig();
    return (
      <Button
        onClick={() =>
          void mutate(
            unstable_serialize(() => [SWR_KEYS.skillVersions(skill.id), null])
          )
        }
      >
        Refresh elsewhere
      </Button>
    );
  }
  render(
    <>
      <RefreshElsewhere />
      <SkillVersions
        skill={skill}
        onBusyChange={jest.fn()}
        onRestored={jest.fn()}
      />
    </>
  );
  const user = setupUser();
  await user.click(
    await screen.findByRole("button", { name: "Load older versions" })
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Could not load versions."
  );
  failOlder = false;
  const elsewhere = screen.getByRole("button", { name: "Refresh elsewhere" });
  await user.click(elsewhere);
  expect(
    await screen.findByRole("button", { name: "Preview version 1" })
  ).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(elsewhere).toHaveFocus();
});

function RevalidateHistory() {
  const { mutate } = useSWRConfig();
  return (
    <Button
      onClick={() =>
        void mutate(
          unstable_serialize(() => [SWR_KEYS.skillVersions(skill.id), null])
        )
      }
    >
      Revalidate history
    </Button>
  );
}

describe.each([401, 402, 403, 404])("history access response %s", (status) => {
  test.each([false, true])(
    "hides cached history and clears previews (preview open: %s)",
    async (openPreview) => {
      let historyStatus = 200;
      let previewResponse: Promise<Response> | undefined;
      fetchMock.mockImplementation(async (url) => {
        if (url === SWR_KEYS.skillVersions(skill.id)) {
          return historyStatus === 200
            ? response(
                versions.map((version) => ({
                  ...version,
                  marketplace_revision: "private-revision",
                }))
              )
            : response({ detail: "Access denied" }, historyStatus);
        }
        if (url === SWR_KEYS.skillVersion(skill.id, "v1"))
          return previewResponse ?? response(bundle);
        throw new Error(`Unexpected request: ${url}`);
      });
      render(
        <>
          <RevalidateHistory />
          <SkillVersions
            skill={{ ...skill, user_permission: "EDITOR" }}
            onBusyChange={jest.fn()}
            onRestored={jest.fn()}
          />
        </>
      );
      const user = setupUser();
      expect(await screen.findByText("owner@example.com")).toBeVisible();
      expect(
        screen.getAllByText("Synced revision private-revision")
      ).toHaveLength(3);
      if (openPreview) {
        await user.click(
          screen.getByRole("button", { name: "Preview version 1" })
        );
        expect(await screen.findByText("Earlier instructions")).toBeVisible();
      }
      historyStatus = status;
      await user.click(
        screen.getByRole("button", { name: "Revalidate history" })
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Could not load versions."
      );
      expect(screen.queryByText("owner@example.com")).not.toBeInTheDocument();
      expect(
        screen.queryByText("Synced revision private-revision")
      ).not.toBeInTheDocument();
      expect(
        screen.queryByText("Earlier instructions")
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /Restore version/ })
      ).not.toBeInTheDocument();
      if (openPreview) {
        const freshPreview = deferred<Response>();
        previewResponse = freshPreview.promise;
        historyStatus = 200;
        await user.click(screen.getByRole("button", { name: "Retry" }));
        await user.click(
          await screen.findByRole("button", { name: "Preview version 1" })
        );
        expect(
          screen.queryByText("Earlier instructions")
        ).not.toBeInTheDocument();
        await act(async () =>
          freshPreview.resolve(
            response({
              ...bundle,
              instructions_markdown: "Freshly authorized instructions",
            })
          )
        );
        expect(
          await screen.findByText("Freshly authorized instructions")
        ).toBeVisible();
      }
    }
  );
});

describe("history access recovery", () => {
  const skill = customFixture({
    user_permission: "EDITOR",
    current_version_number: 3,
  });
  const versions: SkillVersion[] = [3, 2, 1].map((number) => ({
    id: `v${number}`,
    version_number: number,
    created_at: "2026-11-08T12:00:00Z",
    created_by:
      number === 3 ? { id: "owner", email: "owner@example.com" } : null,
    is_current: number === 3,
    has_bundle: true,
    marketplace_revision: "private-revision",
  }));
  const bundle = {
    name: skill.name,
    description: "Earlier description",
    instructions_markdown: "Earlier instructions",
    files: [],
  };
  const response = (data: unknown, status = 200) =>
    new Response(JSON.stringify(data), { status });

  type HistoryMode = number | "network";
  let historyMode: HistoryMode = 200;
  let previewResponses: Promise<Response>[] = [];
  const fetchMock = jest.fn<
    Promise<Response>,
    [RequestInfo | URL, RequestInit?]
  >();

  beforeEach(() => {
    historyMode = 200;
    previewResponses = [];
    fetchMock.mockReset().mockImplementation(async (url) => {
      if (url === SWR_KEYS.skillVersions(skill.id)) {
        if (historyMode === "network") throw new TypeError("Failed to fetch");
        return historyMode === 200
          ? response(versions)
          : response({ detail: "Access denied" }, historyMode);
      }
      if (url === SWR_KEYS.skillVersion(skill.id, "v1"))
        return previewResponses.shift() ?? response(bundle);
      throw new Error(`Unexpected request: ${url}`);
    });
    global.fetch = fetchMock;
  });

  function Harness() {
    const { mutate } = useSWRConfig();
    const [open, setOpen] = useState(true);
    return (
      <>
        <Button
          onClick={() =>
            void mutate(
              unstable_serialize(() => [SWR_KEYS.skillVersions(skill.id), null])
            )
          }
        >
          Revalidate history
        </Button>
        <Button onClick={() => setOpen((value) => !value)}>
          Toggle dialog
        </Button>
        {open && (
          <SkillVersions
            skill={skill}
            onBusyChange={jest.fn()}
            onRestored={jest.fn()}
          />
        )}
      </>
    );
  }

  async function denyAfterLoad(status: number) {
    const user = setupUser();
    render(<Harness />);
    expect(await screen.findByText("owner@example.com")).toBeVisible();
    historyMode = status;
    await user.click(
      screen.getByRole("button", { name: "Revalidate history" })
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load versions."
    );
    expect(screen.queryByText("owner@example.com")).not.toBeInTheDocument();
    return user;
  }

  describe.each([403, 404])("after a %s denial", (status) => {
    test.each<HistoryMode>([503, "network"])(
      "a later %s retry failure keeps the denied rows hidden",
      async (mode) => {
        const user = await denyAfterLoad(status);
        historyMode = mode;
        await user.click(screen.getByRole("button", { name: "Retry" }));
        await waitFor(() =>
          expect(
            fetchMock.mock.calls.filter(
              ([url]) => url === SWR_KEYS.skillVersions(skill.id)
            )
          ).toHaveLength(3)
        );
        // Let SWR commit the failed retry.
        await act(async () => {
          await new Promise((resolve) => setTimeout(resolve, 50));
        });
        expect(screen.queryByText("owner@example.com")).not.toBeInTheDocument();
        expect(
          screen.queryByText("Synced revision private-revision")
        ).not.toBeInTheDocument();
      }
    );

    test("reopening the dialog with a transient failure keeps denied rows hidden", async () => {
      const user = await denyAfterLoad(status);
      await user.click(screen.getByRole("button", { name: "Toggle dialog" }));
      historyMode = 503;
      await user.click(screen.getByRole("button", { name: "Toggle dialog" }));
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 100));
      });
      expect(screen.queryByText("owner@example.com")).not.toBeInTheDocument();
    });
  });

  test("denial on an older page clears every page across remount and retry", async () => {
    const user = setupUser();
    const many: SkillVersion[] = Array.from({ length: 155 }, (_, index) => ({
      id: `many-${155 - index}`,
      version_number: 155 - index,
      created_at: "2026-11-08T12:00:00Z",
      created_by: { id: "creator", email: "retained@example.com" },
      is_current: index === 0,
      has_bundle: true,
      marketplace_revision: "retained-revision",
    }));
    let denyOlder = false;
    let failAll = false;
    fetchMock.mockImplementation(async (input) => {
      if (failAll) return response({ detail: "Unavailable" }, 503);
      const url = new URL(String(input), "http://localhost");
      const cursor = url.searchParams.get("before_version");
      if (cursor && denyOlder) return response({ detail: "Not found" }, 404);
      return response(
        many
          .filter((row) => row.version_number < Number(cursor ?? Infinity))
          .slice(0, 50)
      );
    });
    render(<Harness />);
    await user.click(
      await screen.findByRole("button", { name: "Load older versions" })
    );
    expect(
      await screen.findByRole("button", { name: "Preview version 56" })
    ).toBeVisible();
    denyOlder = true;
    await user.click(
      screen.getByRole("button", { name: "Load older versions" })
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load versions."
    );
    expect(screen.queryByText("retained@example.com")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Toggle dialog" }));
    failAll = true;
    await user.click(screen.getByRole("button", { name: "Toggle dialog" }));
    await user.click(await screen.findByRole("button", { name: "Retry" }));
    expect(
      screen.queryByRole("button", { name: /Preview version/ })
    ).not.toBeInTheDocument();
    expect(screen.queryByText("retained@example.com")).not.toBeInTheDocument();
    failAll = false;
    denyOlder = false;
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByRole("button", { name: "Preview version 155" })
    ).toBeVisible();
  });

  test("a preview requested before a denial does not block the preview after recovery", async () => {
    const user = setupUser();
    const stale = deferred<Response>();
    previewResponses = [stale.promise];
    render(<Harness />);
    await user.click(
      await screen.findByRole("button", { name: "Preview version 1" })
    );
    historyMode = 404;
    await user.click(
      screen.getByRole("button", { name: "Revalidate history" })
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load versions."
    );
    historyMode = 200;
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await user.click(
      await screen.findByRole("button", { name: "Preview version 1" })
    );
    await act(async () => stale.resolve(response(bundle)));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 200));
    });
    expect(
      fetchMock.mock.calls.filter(
        ([url]) => url === SWR_KEYS.skillVersion(skill.id, "v1")
      )
    ).toHaveLength(2);
    expect(screen.getByText("Earlier instructions")).toBeVisible();
  });

  test("control: reopening a preview joins its in-flight request without a denial", async () => {
    const user = setupUser();
    const stale = deferred<Response>();
    previewResponses = [stale.promise];
    render(<Harness />);
    await user.click(
      await screen.findByRole("button", { name: "Preview version 1" })
    );
    await user.click(screen.getByRole("button", { name: "Back" }));
    await user.click(
      await screen.findByRole("button", { name: "Preview version 1" })
    );
    await act(async () => stale.resolve(response(bundle)));
    expect(await screen.findByText("Earlier instructions")).toBeVisible();
  });

  test("app SWR config keeps denied rows hidden during later failures", async () => {
    const { skipRetryOnAuthError } =
      jest.requireActual<typeof import("@/lib/fetcher")>("@/lib/fetcher");
    const user = setupUser();
    render(<Harness />, {
      swrConfig: {
        dedupingInterval: 2000,
        shouldRetryOnError: true,
        onErrorRetry: skipRetryOnAuthError,
      },
    });
    expect(await screen.findByText("owner@example.com")).toBeVisible();
    historyMode = 404;
    await user.click(
      screen.getByRole("button", { name: "Revalidate history" })
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load versions."
    );
    expect(screen.queryByText("owner@example.com")).not.toBeInTheDocument();
    historyMode = 503;
    // skipRetryOnAuthError retries a 404 after 4 seconds without user action.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 4600));
    });
    expect(screen.queryByText("owner@example.com")).not.toBeInTheDocument();
  }, 15000);

  test("app dedupe interval permits a fresh preview after recovery", async () => {
    const user = setupUser();
    render(<Harness />, { swrConfig: { dedupingInterval: 2000 } });
    await user.click(
      await screen.findByRole("button", { name: "Preview version 1" })
    );
    expect(await screen.findByText("Earlier instructions")).toBeVisible();
    historyMode = 404;
    await user.click(
      screen.getByRole("button", { name: "Revalidate history" })
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load versions."
    );
    historyMode = 200;
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await user.click(
      await screen.findByRole("button", { name: "Preview version 1" })
    );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 2500));
    });
    expect(screen.getByText("Earlier instructions")).toBeVisible();
  }, 10000);
});
