import { render, screen, setupUser, within } from "@tests/setup/test-utils";
import { mockFetch, requestBody } from "@tests/setup/integrationTestUtils";
import CustomizeSkillsPage from "@/sections/customize/CustomizeSkillsPage";
import messages from "@/i18n/messages/en.json";
import {
  builtinFixture,
  customFixture,
} from "@/lib/skills/__fixtures__/picker";
import type { ChatSkill } from "@/lib/skills/types";

const copy = messages.customize.skills;

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
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    user: { id: "user-me", email: "me@example.com" },
    isAdmin: false,
  }),
}));

const off = customFixture({
  id: "off-skill",
  name: "standup",
  enabled: false,
  owner: { id: "user-me", email: "me@example.com" },
});

function open(chatSkills: ChatSkill[] = []) {
  window.history.replaceState(null, "", "/app/customize/skills");
  const fetchMock = mockFetch({
    "/api/plugins/chat-skills": chatSkills,
    "/api/plugins": {
      builtins: [builtinFixture({ id: "pptx", name: "pptx" })],
      customs: [
        off,
        customFixture({
          id: "org-skill",
          name: "weekly-report",
          owner: { id: "other", email: "other@example.com" },
          published_version_number: 1,
        }),
      ],
    },
    "PUT /api/plugins/off-skill/enabled": { ...off, enabled: true },
  });
  render(<CustomizeSkillsPage />);
  return fetchMock;
}

afterEach(() => {
  jest.restoreAllMocks();
});

test("lists the skills in groups and hides built-ins that chat does not offer", async () => {
  open();
  const mine = await screen.findByRole("region", { name: copy.groups.mine });
  expect(within(mine).getByText("standup")).toBeInTheDocument();
  expect(
    within(
      screen.getByRole("region", { name: copy.groups.organization })
    ).getByText("weekly-report")
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("region", { name: copy.groups.builtin })
  ).not.toBeInTheDocument();
});

test("shows the built-in skills that chat offers", async () => {
  open([
    {
      name: "pptx",
      description: "Make slides",
      short_description: null,
      version_id: "pptx",
      built_in_skill_id: "pptx",
      plugin_id: null,
    },
  ]);
  const builtins = await screen.findByRole("region", {
    name: copy.groups.builtin,
  });
  expect(within(builtins).getByText("pptx")).toBeInTheDocument();
});

test("Turn on enables a skill that is off", async () => {
  const fetchMock = open();
  const mine = await screen.findByRole("region", { name: copy.groups.mine });
  await setupUser().click(
    within(mine).getByRole("button", { name: copy.menu.turnOn })
  );
  expect(
    requestBody(fetchMock, "PUT", "/api/plugins/off-skill/enabled")
  ).toEqual({ enabled: true, replace_conflict: false });
});

test("a synced skill names its marketplace and whether it is personal", async () => {
  window.history.replaceState(null, "", "/app/customize/skills");
  mockFetch({
    "/api/plugins": {
      builtins: [],
      customs: [
        customFixture({
          id: "synced-skill",
          name: "academy-guide",
          owner: { id: "user-me", email: "me@example.com" },
          marketplace: {
            id: "m-personal",
            name: "anthropic-agent-skills",
            kind: "github",
            repository: "anthropics/skills",
            personal: true,
          },
        }),
      ],
    },
  });
  render(<CustomizeSkillsPage />);

  expect(
    await screen.findByText(/^from anthropic-agent-skills \(personal\)/)
  ).toBeInTheDocument();
});
