import {
  act,
  deferred,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
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
