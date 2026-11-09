import { render, screen, setupUser } from "@tests/setup/test-utils";
import SkillVersions from "@/sections/skills/SkillVersions";
import { customFixture } from "@/lib/skills/__fixtures__/picker";
import type { SkillVersion } from "@/lib/skills/types";
import { SWR_KEYS } from "@/lib/swr-keys";

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
