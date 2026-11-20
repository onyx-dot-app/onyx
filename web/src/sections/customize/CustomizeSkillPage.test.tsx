import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { toast } from "@opal/layouts";
import { mockFetch, requestBody } from "@tests/setup/integrationTestUtils";
import CustomizeSkillPage from "@/sections/customize/CustomizeSkillPage";
import messages from "@/i18n/messages/en.json";
import { customFixture } from "@/lib/skills/__fixtures__/picker";
import type { CustomSkill, SkillEditableDetail } from "@/lib/skills/types";

const copy = messages.customize.skillPage;

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => window.location.pathname,
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({
    isGlobalHolder: false,
    isScopedManager: false,
  }),
}));
// Stages a two-file upload without reading real files.
jest.mock("@/sections/skills/SkillFilesPicker", () => ({
  __esModule: true,
  default: ({
    onChange,
  }: {
    onChange: (upload: {
      file: File;
      displayName: string;
      entries: { path: string; size: number }[];
      containsSkillMd: boolean;
    }) => void;
  }) => (
    <button
      type="button"
      onClick={() =>
        onChange({
          file: new File(["zip"], "pair.zip"),
          displayName: "pair.zip",
          entries: [
            { path: "a.md", size: 1 },
            { path: "b.md", size: 1 },
          ],
          containsSkillMd: false,
        })
      }
    >
      Stage pair
    </button>
  ),
}));
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({ user: { id: "user-me", email: "me@example.com" } }),
}));

function detail(over: Partial<CustomSkill>): SkillEditableDetail {
  return {
    ...customFixture({ id: "custom-1", name: "report-writer", ...over }),
    instructions_markdown: "# Report writer\n\nWrite the report.",
    files: [{ path: "references/guide.md", size: 40 }],
  };
}

function open(
  skill: SkillEditableDetail,
  url = "/app/customize/skills/custom-1",
  from?: "admin"
) {
  window.history.replaceState(null, "", url);
  const fetchMock = mockFetch({
    "/api/skills/custom/custom-1/edit": skill,
    "/api/skills/custom-1/preview": {
      source: "custom",
      id: "custom-1",
      name: skill.name,
      description: skill.description,
      author_email: null,
      instructions_markdown: skill.instructions_markdown,
      files: skill.files,
    },
    "/api/skills": { builtins: [], customs: [skill] },
    "/api/skills/custom/custom-1/versions": [
      {
        id: "version-2",
        version_number: 2,
        created_at: "2026-11-01T10:00:00Z",
        created_by_email: "me@example.com",
        is_current: true,
        review_status: "draft",
      },
      {
        id: "version-1",
        version_number: 1,
        created_at: "2026-10-01T10:00:00Z",
        created_by_email: "me@example.com",
        is_current: false,
        review_status: "draft",
      },
    ],
    "PUT /api/skills/custom-1/enabled": { ...skill, enabled: true },
    "POST /api/skills/custom/custom-1/versions/version-1/restore": {
      ...skill,
      current_version_id: "version-3",
      current_version_number: 3,
    },
  });
  render(<CustomizeSkillPage skillId="custom-1" from={from} />);
  return fetchMock;
}

afterEach(() => jest.restoreAllMocks());

test("an owner sees Overview, Contents and Versions", async () => {
  open(
    detail({
      user_permission: "OWNER",
      owner: { id: "user-me", email: "me@example.com" },
    })
  );
  const user = setupUser();
  expect(
    await screen.findByRole("tab", { name: copy.tabs.overview })
  ).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("tab", { name: "Contents · 2" })).toBeVisible();
  await user.click(screen.getByRole("tab", { name: copy.tabs.versions }));
  expect(await screen.findByText("Version 2")).toBeVisible();
});

test("a viewer has no Versions tab and no Share", async () => {
  open(
    detail({
      user_permission: "VIEWER",
      owner: { id: "other", email: "other@example.com" },
    })
  );
  expect(
    await screen.findByRole("tab", { name: copy.tabs.overview })
  ).toBeVisible();
  expect(
    screen.queryByRole("tab", { name: copy.tabs.versions })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: copy.share })
  ).not.toBeInTheDocument();
});

test("a viewer sees the supporting files on the Contents tab", async () => {
  open(
    detail({
      user_permission: "VIEWER",
      owner: { id: "other", email: "other@example.com" },
    }),
    "/app/customize/skills/custom-1?tab=contents"
  );
  expect(
    await screen.findByRole("button", { name: "references/guide.md" })
  ).toBeVisible();
});

test("a viewer who opens a Versions link sees Overview", async () => {
  open(
    detail({
      user_permission: "VIEWER",
      owner: { id: "other", email: "other@example.com" },
    }),
    "/app/customize/skills/custom-1?tab=versions"
  );
  expect(
    await screen.findByRole("tab", { name: copy.tabs.overview })
  ).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText(copy.overview.createdBy)).toBeVisible();
});

test("an owner edits SKILL.md and removes a file, then saves one edit", async () => {
  const fetchMock = mockFetch({
    "/api/skills/custom/custom-1/edit": {
      ...detail({ user_permission: "OWNER", current_version_id: "version-2" }),
    },
    "/api/skills": {
      builtins: [],
      customs: [detail({ user_permission: "OWNER" })],
    },
    "/api/skills/chat": [],
    "/api/skills/users-over-limit": { users: [] },
    "PATCH /api/skills/custom/custom-1": {
      ...detail({ user_permission: "OWNER" }),
      current_version_id: "version-3",
    },
    "DELETE /api/skills/custom/custom-1/files?path=references%2Fguide.md&base_version_id=version-3":
      {
        ...detail({ user_permission: "OWNER" }),
        current_version_id: "version-4",
      },
  });
  window.history.replaceState(
    null,
    "",
    "/app/customize/skills/custom-1?edit=1"
  );
  render(<CustomizeSkillPage skillId="custom-1" />);
  const user = setupUser();

  const editor = await screen.findByRole("textbox", {
    name: copy.contents.editorLabel,
  });
  expect(editor).toHaveValue(
    '---\nname: "report-writer"\ndescription: "Draft a structured report from notes."\n---\n\n# Report writer\n\nWrite the report.'
  );
  await user.clear(editor);
  await user.type(
    editor,
    '---\nname: "report-writer"\ndescription: "Writes the weekly report."\n---\n\nWrite it.'
  );
  await user.click(screen.getByRole("button", { name: "references/guide.md" }));
  await user.click(
    screen.getByRole("button", {
      name: "Remove references/guide.md",
    })
  );
  expect(
    screen.queryByRole("button", { name: "references/guide.md" })
  ).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: copy.contents.saveVersion })
  );

  await waitFor(() => expect(window.location.search).toBe("?tab=contents"));
  expect(
    requestBody(fetchMock, "PATCH", "/api/skills/custom/custom-1")
  ).toEqual({
    description: "Writes the weekly report.",
    instructions_markdown: "Write it.",
    base_version_id: "version-2",
  });
});

function ownerRoutes(extra: Record<string, unknown>) {
  const owner = detail({
    user_permission: "OWNER",
    current_version_id: "version-2",
  });
  return mockFetch({
    "/api/skills/custom/custom-1/edit": owner,
    "/api/skills": { builtins: [], customs: [owner] },
    "/api/skills/chat": [],
    "/api/skills/users-over-limit": { users: [] },
    ...extra,
  });
}

async function editDescription(description: string) {
  const user = setupUser();
  const editor = await screen.findByRole("textbox", {
    name: copy.contents.editorLabel,
  });
  await user.clear(editor);
  await user.type(
    editor,
    `---\nname: "report-writer"\ndescription: "${description}"\n---\n\nWrite it.`
  );
  return user;
}

test("a newer save by someone else keeps the draft and offers Reload", async () => {
  ownerRoutes({
    "PATCH /api/skills/custom/custom-1": () =>
      new Response(
        JSON.stringify({ error_code: "PLUGIN_VERSION_STALE", detail: "stale" }),
        { status: 409 }
      ),
  });
  window.history.replaceState(
    null,
    "",
    "/app/customize/skills/custom-1?edit=1"
  );
  render(<CustomizeSkillPage skillId="custom-1" />);
  const user = await editDescription("Mine.");
  await user.click(
    screen.getByRole("button", { name: copy.contents.saveVersion })
  );

  expect(
    await screen.findByText(messages.skills.editor.staleVersion.title)
  ).toBeVisible();
  expect(
    screen.getByRole("textbox", { name: copy.contents.editorLabel })
  ).toHaveValue(
    '---\nname: "report-writer"\ndescription: "Mine."\n---\n\nWrite it.'
  );
  expect(
    screen.getByRole("button", { name: copy.contents.saveVersion })
  ).toBeDisabled();
});

test("Reload drops the staged file changes with the text", async () => {
  ownerRoutes({
    "DELETE /api/skills/custom/custom-1/files?path=references%2Fguide.md&base_version_id=version-2":
      () =>
        new Response(
          JSON.stringify({
            error_code: "PLUGIN_VERSION_STALE",
            detail: "stale",
          }),
          { status: 409 }
        ),
  });
  window.history.replaceState(
    null,
    "",
    "/app/customize/skills/custom-1?edit=1"
  );
  render(<CustomizeSkillPage skillId="custom-1" />);
  const user = setupUser();
  await user.click(
    await screen.findByRole("button", { name: "references/guide.md" })
  );
  await user.click(
    screen.getByRole("button", { name: "Remove references/guide.md" })
  );
  const save = screen.getByRole("button", { name: copy.contents.saveVersion });
  await user.click(save);
  await user.click(
    await screen.findByRole("button", {
      name: messages.skills.editor.staleVersion.reload.label,
    })
  );

  expect(
    await screen.findByRole("button", { name: "references/guide.md" })
  ).toBeVisible();
  await waitFor(() => expect(save).toBeDisabled());
});

test("a failed refresh keeps the page and the editor", async () => {
  const toastError = jest.spyOn(toast, "error");
  let reads = 0;
  ownerRoutes({
    "/api/skills/custom/custom-1/edit": () => {
      reads += 1;
      return reads === 1
        ? detail({ user_permission: "OWNER", current_version_id: "version-2" })
        : new Response(JSON.stringify({ detail: "down" }), { status: 503 });
    },
    "PATCH /api/skills/custom/custom-1": () =>
      new Response(
        JSON.stringify({ error_code: "PLUGIN_VERSION_STALE", detail: "stale" }),
        { status: 409 }
      ),
  });
  window.history.replaceState(
    null,
    "",
    "/app/customize/skills/custom-1?edit=1"
  );
  render(<CustomizeSkillPage skillId="custom-1" />);
  const user = await editDescription("Mine.");
  await user.click(
    screen.getByRole("button", { name: copy.contents.saveVersion })
  );
  await user.click(
    await screen.findByRole("button", {
      name: messages.skills.editor.staleVersion.reload.label,
    })
  );

  await waitFor(() => expect(reads).toBeGreaterThan(1));
  expect(screen.queryByText(copy.loadFailed)).not.toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /^Contents/ })).toBeVisible();
  await waitFor(() =>
    expect(toastError).toHaveBeenCalledWith(copy.contents.reloadFailed)
  );
  expect(
    screen.getByRole("textbox", { name: copy.contents.editorLabel })
  ).toHaveValue(
    '---\nname: "report-writer"\ndescription: "Mine."\n---\n\nWrite it.'
  );
  expect(
    screen.getByText(messages.skills.editor.staleVersion.title)
  ).toBeVisible();
});

test("a retry after a failed step sends only the steps left", async () => {
  let removals = 0;
  const fetchMock = ownerRoutes({
    "PATCH /api/skills/custom/custom-1": {
      ...detail({ user_permission: "OWNER" }),
      current_version_id: "version-3",
    },
    "DELETE /api/skills/custom/custom-1/files?path=references%2Fguide.md&base_version_id=version-3":
      () => {
        removals += 1;
        return removals === 1
          ? new Response(JSON.stringify({ detail: "busy" }), { status: 503 })
          : {
              ...detail({ user_permission: "OWNER" }),
              current_version_id: "version-4",
            };
      },
  });
  window.history.replaceState(
    null,
    "",
    "/app/customize/skills/custom-1?edit=1"
  );
  render(<CustomizeSkillPage skillId="custom-1" />);
  const user = await editDescription("Writes the weekly report.");
  await user.click(screen.getByRole("button", { name: "references/guide.md" }));
  await user.click(
    screen.getByRole("button", { name: "Remove references/guide.md" })
  );
  const save = screen.getByRole("button", { name: copy.contents.saveVersion });
  await user.click(save);
  await waitFor(() => expect(removals).toBe(1));
  await waitFor(() => expect(save).toBeEnabled());

  await user.click(save);
  await waitFor(() => expect(window.location.search).toBe("?tab=contents"));
  expect(
    fetchMock.mock.calls.filter(([, init]) => init?.method === "PATCH")
  ).toHaveLength(1);
  expect(removals).toBe(2);
});

test("a retry still removes a file from an upload that already went up", async () => {
  let removals = 0;
  ownerRoutes({
    "POST /api/skills/custom/custom-1/files": {
      ...detail({ user_permission: "OWNER" }),
      current_version_id: "version-3",
    },
    "DELETE /api/skills/custom/custom-1/files?path=b.md&base_version_id=version-3":
      () => {
        removals += 1;
        return removals === 1
          ? new Response(JSON.stringify({ detail: "busy" }), { status: 503 })
          : {
              ...detail({ user_permission: "OWNER" }),
              current_version_id: "version-4",
            };
      },
  });
  window.history.replaceState(
    null,
    "",
    "/app/customize/skills/custom-1?edit=1"
  );
  render(<CustomizeSkillPage skillId="custom-1" />);
  const user = setupUser();
  await user.click(await screen.findByRole("button", { name: "Stage pair" }));
  await user.click(screen.getByRole("button", { name: "b.md" }));
  await user.click(screen.getByRole("button", { name: "Remove b.md" }));
  const save = screen.getByRole("button", { name: copy.contents.saveVersion });
  await user.click(save);
  await waitFor(() => expect(removals).toBe(1));
  await waitFor(() => expect(save).toBeEnabled());

  await user.click(save);
  await waitFor(() => expect(removals).toBe(2));
});

test("leaving edits by a tab asks first", async () => {
  ownerRoutes({});
  window.history.replaceState(
    null,
    "",
    "/app/customize/skills/custom-1?edit=1"
  );
  render(<CustomizeSkillPage skillId="custom-1" />);
  const user = await editDescription("Changed.");
  await user.click(screen.getByRole("tab", { name: copy.tabs.overview }));

  expect(await screen.findByRole("dialog")).toBeVisible();
  expect(window.location.search).toBe("?edit=1");
});

test("a renamed skill in SKILL.md is refused before any save", async () => {
  const fetchMock = mockFetch({
    "/api/skills/custom/custom-1/edit": detail({ user_permission: "OWNER" }),
    "/api/skills": {
      builtins: [],
      customs: [detail({ user_permission: "OWNER" })],
    },
  });
  const toastError = jest.spyOn(toast, "error");
  window.history.replaceState(
    null,
    "",
    "/app/customize/skills/custom-1?edit=1"
  );
  render(<CustomizeSkillPage skillId="custom-1" />);
  const user = setupUser();
  const editor = await screen.findByRole("textbox", {
    name: copy.contents.editorLabel,
  });
  await user.clear(editor);
  await user.type(editor, '---\nname: "other"\ndescription: "d"\n---\n\nbody');
  await user.click(
    screen.getByRole("button", { name: copy.contents.saveVersion })
  );
  expect(toastError).toHaveBeenCalledWith(
    'The name must stay "report-writer".'
  );
  expect(
    fetchMock.mock.calls.some(([, init]) => init?.method === "PATCH")
  ).toBe(false);
});

test("an admin who changes tabs stays on the admin skill page", async () => {
  open(
    detail({
      user_permission: "OWNER",
      owner: { id: "user-me", email: "me@example.com" },
    }),
    "/admin/skills/custom-1",
    "admin"
  );
  const user = setupUser();
  await user.click(await screen.findByRole("tab", { name: /^Contents/ }));
  await waitFor(() =>
    expect(window.location.pathname + window.location.search).toBe(
      "/admin/skills/custom-1?tab=contents"
    )
  );
});

test("a failed preview keeps the Overview and shows the error in Contents", async () => {
  const viewer = detail({
    user_permission: "VIEWER",
    owner: { id: "other", email: "other@example.com" },
  });
  mockFetch({
    "/api/skills": { builtins: [], customs: [viewer] },
    "/api/skills/custom-1/preview": () =>
      new Response(JSON.stringify({ detail: "down" }), { status: 503 }),
  });
  window.history.replaceState(null, "", "/app/customize/skills/custom-1");
  render(<CustomizeSkillPage skillId="custom-1" />);
  const user = setupUser();

  expect(await screen.findByText(copy.overview.createdBy)).toBeVisible();
  await user.click(screen.getByRole("tab", { name: /^Contents/ }));
  expect(await screen.findByText(copy.contents.loadFailed)).toBeVisible();
});

test("Add turns on an organization skill the user has not added", async () => {
  const fetchMock = open(
    detail({
      user_permission: "VIEWER",
      owner: { id: "other", email: "other@example.com" },
      published_version_number: 1,
      enabled: false,
      can_toggle: true,
    })
  );
  expect(await screen.findByText(copy.fromOrganization)).toBeVisible();
  await setupUser().click(screen.getByRole("button", { name: copy.add }));
  expect(requestBody(fetchMock, "PUT", "/api/skills/custom-1/enabled")).toEqual(
    { enabled: true, replace_conflict: false }
  );
});

test("an owner restores a version from the Versions tab", async () => {
  const fetchMock = open(
    detail({
      user_permission: "OWNER",
      owner: { id: "user-me", email: "me@example.com" },
      current_version_id: "version-2",
      current_version_number: 2,
    })
  );
  const user = setupUser();
  await user.click(
    await screen.findByRole("tab", { name: copy.tabs.versions })
  );
  await user.click(
    await screen.findByRole("button", { name: "Restore version 1" })
  );
  expect(
    requestBody(
      fetchMock,
      "POST",
      "/api/skills/custom/custom-1/versions/version-1/restore"
    )
  ).toEqual({ base_version_id: "version-2" });
});

test("a skill synced from GitHub offers no content changes, and says why", async () => {
  open(
    detail({
      user_permission: "OWNER",
      owner: { id: "user-me", email: "me@example.com" },
      can_delete: false,
      content_locked: true,
      marketplace: {
        id: "market-1",
        name: "acme/plugins",
        kind: "github",
        repository: "acme/plugins",
        personal: false,
      },
    }),
    "/app/customize/skills/custom-1?edit=1"
  );
  const user = setupUser();
  const lockedCopy = messages.skills.modals.versions.locked;

  expect(
    await screen.findByRole("tab", { name: copy.tabs.overview })
  ).toHaveAttribute("aria-selected", "true");
  await user.click(screen.getByRole("tab", { name: "Contents · 2" }));
  expect(await screen.findByText(lockedCopy)).toBeVisible();
  expect(
    screen.queryByRole("button", { name: copy.contents.edit })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: copy.contents.saveVersion })
  ).not.toBeInTheDocument();

  expect(screen.getByRole("button", { name: copy.share })).toBeVisible();
  expect(
    screen.queryByRole("button", { name: copy.menu })
  ).not.toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: copy.tabs.versions }));
  expect(await screen.findByText("Version 1")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "Restore version 1" })
  ).not.toBeInTheDocument();
});

test("an uploaded plugin opens its plugin page without skill-only requests", async () => {
  window.history.replaceState(null, "", "/admin/skills/custom-1");
  const plugin = customFixture({
    id: "custom-1",
    name: "review-kit",
    kind: "plugin",
    user_permission: "OWNER",
  });
  const fetchMock = mockFetch({
    "/api/skills": { builtins: [], customs: [plugin] },
  });
  render(<CustomizeSkillPage skillId="custom-1" from="admin" />);
  await waitFor(() =>
    expect(window.location.pathname).toBe("/app/customize/plugins/custom-1")
  );
  expect(
    fetchMock.mock.calls
      .map(([input]) => String(input))
      .filter((url) => url.startsWith("/api/skills/"))
  ).toEqual([]);
});
