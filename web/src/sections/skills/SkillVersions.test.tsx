import {
  act,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import useSWR from "swr";
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

test.each([
  { number: 3, failLibrary: false },
  { number: 4, failLibrary: false },
  { number: 4, failLibrary: true },
])(
  "refreshes restored content (version $number, library failure $failLibrary)",
  async ({ number, failLibrary }) => {
    let didRestore = false;
    const result = { ...restored, current_version_number: number };
    fetchMock.mockImplementation(async (url, init) => {
      if (init?.method === "POST") {
        didRestore = true;
        return response(result);
      }
      const requestUrl = new URL(String(url), "http://localhost");
      if (requestUrl.pathname === SWR_KEYS.skillVersions(skill.id)) {
        const before = Number(
          requestUrl.searchParams.get("before_version") ?? Infinity
        );
        return response(
          (didRestore
            ? [
                { ...versions[0], id: "current", version_number: number },
                ...versions
                  .filter((version) => version.version_number < number)
                  .map((version) => ({ ...version, is_current: false })),
              ]
            : versions
          )
            .filter((version) => version.version_number < before)
            .slice(0, didRestore ? 1 : 50)
        );
      }
      if (url === SWR_KEYS.userSkills)
        return didRestore && failLibrary
          ? response({ detail: "Unavailable" }, 503)
          : response({
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
      await within(screen.getByRole("table")).findByText("Initial version")
    ).toBeVisible();
    expect(
      fetchMock.mock.calls.some(([url]) => {
        const request = new URL(String(url), "http://localhost");
        return (
          request.pathname === SWR_KEYS.skillVersions(skill.id) &&
          request.searchParams.get("before_version") === String(number)
        );
      })
    ).toBe(true);
  }
);

test.each([
  { failures: 1, loadOlder: false, status: 503 },
  { failures: 2, loadOlder: false, status: 503 },
  { failures: 2, loadOlder: true, status: 503 },
  { failures: 1, loadOlder: true, status: 0 },
  { failures: 1, loadOlder: true, status: 403 },
])(
  "recovers history after $failures refresh failures (older: $loadOlder, status: $status)",
  async ({ failures, loadOlder, status }) => {
    const history: SkillVersion[] = Array.from({ length: 100 }, (_, index) => ({
      id: `v${100 - index}`,
      version_number: 100 - index,
      created_at: "2026-11-08T12:00:00Z",
      created_by: null,
      is_current: index === 0,
      has_bundle: true,
      marketplace_revision: null,
    }));
    let didRestore = false;
    let failedReads = 0;
    fetchMock.mockImplementation(async (input, init) => {
      if (init?.method === "POST") {
        didRestore = true;
        const latest = history[0];
        if (!latest) throw new Error("Missing current version");
        history.unshift({ ...latest, id: "v101", version_number: 101 });
        return response({ ...restored, current_version_number: 101 });
      }
      const url = new URL(String(input), "http://localhost");
      if (url.pathname === SWR_KEYS.skillVersions(skill.id)) {
        if (
          didRestore &&
          failedReads < failures &&
          (!loadOlder || url.searchParams.has("before_version"))
        ) {
          failedReads += 1;
          if (!status) throw new TypeError("Network unavailable");
          return response({ detail: "Unavailable" }, status);
        }
        const before = Number(
          url.searchParams.get("before_version") ?? Infinity
        );
        return response(
          history.filter((row) => row.version_number < before).slice(0, 50)
        );
      }
      return response(bundle);
    });
    const user = setupUser();
    showHistory();
    if (loadOlder) {
      await user.click(
        await screen.findByRole("button", { name: "Load older versions" })
      );
      await screen.findByRole("button", { name: "Preview version 1" });
    }
    await user.click(
      await screen.findByRole("button", {
        name: `Restore version ${loadOlder ? 1 : 51}`,
      })
    );
    await user.click(screen.getByRole("button", { name: "Restore" }));
    if (status !== 403) await screen.findByRole("status");
    else
      await waitFor(() =>
        expect(
          screen.queryByRole("button", { name: /Preview version/ })
        ).not.toBeInTheDocument()
      );
    for (let attempt = 1; attempt <= failures; attempt += 1) {
      await waitFor(() => expect(failedReads).toBe(attempt));
      await user.click(await screen.findByRole("button", { name: "Retry" }));
    }
    await screen.findByRole("button", { name: "Preview version 101" });
    if (status !== 403)
      expect(
        await screen.findByRole("button", {
          name: `Preview version ${loadOlder ? 1 : 51}`,
        })
      ).toBeVisible();
  }
);
