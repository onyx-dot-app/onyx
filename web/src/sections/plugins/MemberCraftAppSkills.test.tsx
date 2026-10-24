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

test("shows only this app's built-in and custom skills with preview and enable controls", async () => {
  jest.spyOn(global, "fetch").mockResolvedValue(jsonResponse(skills));
  render(
    <MemberCraftAppSkills
      appId={6}
      changes={{}}
      onChange={jest.fn()}
      disabled={false}
      onPreview={jest.fn()}
    />
  );
  const builtin = (await screen.findByText("linear-issues")).closest("li");
  const custom = screen.getByText("release-notes").closest("li");
  expect(builtin).not.toBeNull();
  expect(custom).not.toBeNull();
  if (!builtin || !custom) throw new Error("Missing skill rows");
  expect(within(builtin).getByRole("switch")).toBeChecked();
  expect(within(custom).getByRole("switch")).not.toBeChecked();
  expect(screen.queryByText("slides")).not.toBeInTheDocument();
  expect(screen.queryByText("github-releases")).not.toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "Preview" })).toHaveLength(2);
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
});

test("search matches descriptions and clearing restores the app's skills", async () => {
  jest.spyOn(global, "fetch").mockResolvedValue(jsonResponse(skills));
  render(
    <MemberCraftAppSkills
      appId={6}
      changes={{}}
      onChange={jest.fn()}
      disabled={false}
      onPreview={jest.fn()}
    />
  );
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
  render(
    <MemberCraftAppSkills
      appId={42}
      changes={{}}
      onChange={jest.fn()}
      disabled={false}
      onPreview={jest.fn()}
    />
  );
  expect(
    await screen.findByText("No skills are associated with this app.")
  ).toBeVisible();
});

test("shows loading, then recovers from a failed request through Retry", async () => {
  jest
    .spyOn(global, "fetch")
    .mockResolvedValueOnce(jsonResponse({ detail: "Unavailable" }, 503))
    .mockResolvedValue(jsonResponse(skills));
  render(
    <MemberCraftAppSkills
      appId={6}
      changes={{}}
      onChange={jest.fn()}
      disabled={false}
      onPreview={jest.fn()}
    />
  );
  expect(screen.getByRole("status")).toBeVisible();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Skills could not load."
  );
  await setupUser().click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("linear-issues")).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("preview delegates to the modal without changing enablement", async () => {
  jest.spyOn(global, "fetch").mockResolvedValue(jsonResponse(skills));
  const onPreview = jest.fn();
  const onChange = jest.fn();
  render(
    <MemberCraftAppSkills
      appId={6}
      changes={{}}
      onChange={onChange}
      disabled={false}
      onPreview={onPreview}
    />
  );
  const row = (await screen.findByText("release-notes")).closest("li");
  if (!row) throw new Error("Missing skill row");
  await setupUser().click(within(row).getByRole("button", { name: "Preview" }));
  expect(onPreview).toHaveBeenCalledWith(skills.customs[0]);
  expect(onChange).not.toHaveBeenCalled();
});

test("enablement delegates a draft change without writing and reflects the parent draft", async () => {
  const requests = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(jsonResponse(skills));
  const onChange = jest.fn();
  const props = { appId: 6, onChange, disabled: false, onPreview: jest.fn() };
  const { rerender } = render(<MemberCraftAppSkills {...props} changes={{}} />);
  const toggle = await screen.findByRole("switch", {
    name: "Enable release-notes",
  });
  await setupUser().click(toggle);
  expect(onChange).toHaveBeenCalledWith(skills.customs[0], true);
  expect(
    requests.mock.calls.every(
      ([, init]) => !init?.method || init.method === "GET"
    )
  ).toBe(true);
  rerender(
    <MemberCraftAppSkills
      {...props}
      changes={{ [skills.customs[0]!.id]: true }}
    />
  );
  expect(
    screen.getByRole("switch", { name: "Disable release-notes" })
  ).toBeChecked();
});

test("invalid and non-toggleable skills retain Preview but cannot change enablement", async () => {
  jest.spyOn(global, "fetch").mockResolvedValue(
    jsonResponse({
      builtins: [{ ...skills.builtins[0], can_toggle: false }],
      customs: [{ ...skills.customs[0], is_valid: false }],
    })
  );
  const onChange = jest.fn();
  render(
    <MemberCraftAppSkills
      appId={6}
      changes={{}}
      onChange={onChange}
      disabled={false}
      onPreview={jest.fn()}
    />
  );
  await screen.findByText("linear-issues");
  const user = setupUser();
  for (const toggle of screen.getAllByRole("switch")) {
    expect(toggle).toHaveAttribute("aria-disabled", "true");
    await user.click(toggle);
  }
  expect(onChange).not.toHaveBeenCalled();
  for (const preview of screen.getAllByRole("button", { name: "Preview" }))
    expect(preview).toBeEnabled();
});
