import { render, screen, setupUser, within } from "@tests/setup/test-utils";
import MemberCraftAppSkills from "@/sections/plugins/MemberCraftAppSkills";
import {
  builtinFixture,
  customFixture,
} from "@/lib/skills/__fixtures__/picker";
import { jsonResponse } from "@/sections/plugins/__tests__/memberPluginFixtures";

const externalApp = {
  external_app_id: 6,
  name: "Linear",
  enabled: true,
  ready: true,
};

const skills = {
  builtins: [
    builtinFixture({
      name: "linear-issues",
      description: "Find and update issues.",
      external_app: externalApp,
    }),
    builtinFixture({ id: "unrelated", name: "slides" }),
  ],
  customs: [
    customFixture({
      name: "release-notes",
      description: "Write weekly release notes.",
      enabled: false,
      external_app: externalApp,
    }),
    customFixture({
      id: "other-app",
      name: "github-releases",
      external_app: { ...externalApp, external_app_id: 7 },
    }),
  ],
};

afterEach(() => jest.restoreAllMocks());

test("shows only this app's built-in and custom skills with read-only status", async () => {
  jest.spyOn(global, "fetch").mockResolvedValue(jsonResponse(skills));
  render(<MemberCraftAppSkills appId={6} />);
  const builtin = (await screen.findByText("linear-issues")).closest("li");
  const custom = screen.getByText("release-notes").closest("li");
  expect(builtin).not.toBeNull();
  expect(custom).not.toBeNull();
  if (!builtin || !custom) throw new Error("Missing skill rows");
  expect(within(builtin).getByText("Enabled")).toBeVisible();
  expect(within(custom).getByText("Disabled")).toBeVisible();
  expect(screen.queryByText("slides")).not.toBeInTheDocument();
  expect(screen.queryByText("github-releases")).not.toBeInTheDocument();
  expect(screen.queryByRole("switch")).not.toBeInTheDocument();
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
});

test("search matches descriptions and clearing restores the app's skills", async () => {
  jest.spyOn(global, "fetch").mockResolvedValue(jsonResponse(skills));
  render(<MemberCraftAppSkills appId={6} />);
  await screen.findByText("linear-issues");
  const user = setupUser();
  const search = screen.getByRole("textbox", { name: "Search skills" });
  await user.type(search, "WEEKLY");
  expect(screen.getByText("release-notes")).toBeVisible();
  expect(screen.queryByText("linear-issues")).not.toBeInTheDocument();
  await user.clear(search);
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
  await user.type(search, "missing");
  expect(screen.getByText("No skills match your search.")).toBeVisible();
});

test("shows an empty state when no skill depends on this app", async () => {
  jest.spyOn(global, "fetch").mockResolvedValue(jsonResponse(skills));
  render(<MemberCraftAppSkills appId={42} />);
  expect(
    await screen.findByText("No skills are associated with this app.")
  ).toBeVisible();
});

test("shows loading, then recovers from a failed request through Retry", async () => {
  jest
    .spyOn(global, "fetch")
    .mockResolvedValueOnce(jsonResponse({ detail: "Unavailable" }, 503))
    .mockResolvedValue(jsonResponse(skills));
  render(<MemberCraftAppSkills appId={6} />);
  expect(screen.getByRole("status")).toBeVisible();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Skills could not load."
  );
  await setupUser().click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("linear-issues")).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
