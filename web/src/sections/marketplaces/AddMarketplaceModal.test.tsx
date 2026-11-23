import { PointerEventsCheckLevel } from "@testing-library/user-event";
import { render, screen, setupUser, within } from "@tests/setup/test-utils";
import { mockFetch, requestBody } from "@tests/setup/integrationTestUtils";
import AddMarketplaceModal from "@/sections/marketplaces/AddMarketplaceModal";
import {
  detailFixture,
  previewFixture,
} from "@/sections/marketplaces/__fixtures__/marketplace";

let mockIsManager = false;
jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({
    isGlobalHolder: mockIsManager,
    isScopedManager: false,
  }),
}));

afterEach(() => {
  mockIsManager = false;
  jest.restoreAllMocks();
});

async function resolveSource() {
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  await user.type(screen.getByLabelText("Repository"), "acme/plugins");
  await user.type(screen.getByLabelText("Folder"), "catalog");
  await user.type(screen.getByLabelText("Branch, Tag or Commit"), "main");
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await screen.findByText("Confirm Marketplace");
  return user;
}

test("shows the resolved source and the plugins before it adds a personal marketplace", async () => {
  const fetchMock = mockFetch({
    "POST /api/marketplaces/preview": previewFixture(),
    "POST /api/marketplaces": detailFixture(),
  });
  const onAdded = jest.fn();
  render(<AddMarketplaceModal open onClose={jest.fn()} onAdded={onAdded} />);

  const user = await resolveSource();

  expect(requestBody(fetchMock, "POST", "/api/marketplaces/preview")).toEqual({
    repository: "acme/plugins",
    folder: "catalog",
    ref: "main",
  });
  expect(screen.getByText("acme/plugins")).toBeInTheDocument();
  expect(screen.getByText("catalog")).toBeInTheDocument();
  expect(screen.getByText("b".repeat(12))).toBeInTheDocument();
  expect(screen.getByText("acme-plugins: 1 plugin to add")).toBeInTheDocument();
  expect(screen.getByText("Will install")).toBeInTheDocument();
  expect(screen.getByText("Skills: review, summarize")).toBeInTheDocument();
  expect(screen.getByText("linear")).toBeInTheDocument();
  expect(screen.queryByText("Cannot install")).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: /that Onyx cannot use$/ })
  );
  expect(screen.getByText("The plugin has no skills.")).toBeInTheDocument();
  expect(screen.getByText("Cannot install")).toBeInTheDocument();
  expect(screen.queryByText("Marketplace Type")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Add marketplace" }));

  expect(requestBody(fetchMock, "POST", "/api/marketplaces")).toEqual({
    repository: "acme/plugins",
    folder: "catalog",
    ref: "main",
    scope: "personal",
    name: "acme-plugins",
    default_installation_policy: null,
  });
  expect(onAdded).toHaveBeenCalledWith(detailFixture());
});

test("a plugin manager adds a company marketplace with a default access", async () => {
  mockIsManager = true;
  const fetchMock = mockFetch({
    "POST /api/marketplaces/preview": previewFixture(),
    "POST /api/marketplaces": detailFixture({ scope: "company" }),
  });
  render(<AddMarketplaceModal open onClose={jest.fn()} onAdded={jest.fn()} />);
  const user = await resolveSource();

  await user.click(screen.getByRole("combobox", { name: "Marketplace Type" }));
  await user.click(screen.getByRole("option", { name: /Company/ }));
  await user.click(screen.getByRole("combobox", { name: "Default Access" }));
  await user.click(screen.getByRole("option", { name: /Not available/ }));
  await user.click(screen.getByRole("button", { name: "Add marketplace" }));

  expect(requestBody(fetchMock, "POST", "/api/marketplaces")).toMatchObject({
    scope: "company",
    default_installation_policy: "NOT_AVAILABLE",
  });
});

test("a failed read shows its reason and cannot be added", async () => {
  mockFetch({
    "POST /api/marketplaces/preview": previewFixture({
      status: "failed",
      name: null,
      reason: "No .claude-plugin/marketplace.json in catalog.",
      entries: [],
    }),
  });
  render(<AddMarketplaceModal open onClose={jest.fn()} onAdded={jest.fn()} />);
  const user = await resolveSource();

  const alert = screen.getByText("Onyx cannot read this marketplace");
  expect(alert).toBeInTheDocument();
  expect(
    screen.getByText("No .claude-plugin/marketplace.json in catalog.")
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Add marketplace" })
  ).toBeDisabled();

  await user.click(screen.getByRole("button", { name: "Back" }));
  expect(screen.getByLabelText("Repository")).toHaveValue("acme/plugins");
});

test("a GitHub error shows the server message", async () => {
  mockFetch({
    "POST /api/marketplaces/preview": () =>
      new Response(JSON.stringify({ detail: "Repository not found." }), {
        status: 404,
      }),
  });
  render(<AddMarketplaceModal open onClose={jest.fn()} onAdded={jest.fn()} />);
  const user = setupUser();
  await user.type(screen.getByLabelText("Repository"), "acme/missing");
  await user.click(screen.getByRole("button", { name: "Continue" }));

  expect(
    within(await screen.findByRole("alert")).getByText("Repository not found.")
  ).toBeInTheDocument();
});

test("a marketplace that is already added says so and cannot be added again", async () => {
  mockFetch({
    "POST /api/marketplaces/preview": previewFixture({ added_personal: true }),
  });
  render(<AddMarketplaceModal open onClose={jest.fn()} onAdded={jest.fn()} />);
  await resolveSource();

  expect(
    screen.getByText("You already added this marketplace.")
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Add marketplace" })
  ).toBeDisabled();
});

test("GitHub's rate limit says when it resets", async () => {
  mockFetch({
    "POST /api/marketplaces/preview": () =>
      new Response(
        JSON.stringify({
          error_code: "RATE_LIMITED",
          detail: "GitHub's API rate limit has been reached.",
          reset_at: "2027-01-15T08:00:00+00:00",
        }),
        { status: 429 }
      ),
  });
  render(<AddMarketplaceModal open onClose={jest.fn()} onAdded={jest.fn()} />);
  const user = setupUser();
  await user.type(screen.getByLabelText("Repository"), "acme/plugins");
  await user.click(screen.getByRole("button", { name: "Continue" }));

  expect(
    within(await screen.findByRole("alert")).getByText(
      /^GitHub's API rate limit has been reached\. It resets at .+\. Connect GitHub to raise the limit\.$/
    )
  ).toBeInTheDocument();
});

test("entries past the external repository limit share one note", async () => {
  const limited = {
    path: null,
    status: "blocked" as const,
    reason: "Connect GitHub to sync more than 20 external repositories.",
    reason_code: "external_repository_limit_without_login" as const,
    description: null,
    version: null,
    skills: [],
    needs: [],
    warnings: [],
  };
  const preview = previewFixture();
  mockFetch({
    "POST /api/marketplaces/preview": {
      ...preview,
      entries: [
        ...preview.entries,
        { ...limited, key: "remote-one" },
        { ...limited, key: "remote-two" },
        {
          ...limited,
          key: "commands-only",
          status: "not_supported" as const,
          reason: "Onyx runs only skills and MCP servers.",
          reason_code: "skills_and_mcp_only" as const,
        },
      ],
    },
  });
  render(<AddMarketplaceModal open onClose={jest.fn()} onAdded={jest.fn()} />);
  const user = await resolveSource();

  expect(
    screen.getByText("1 Ready · 3 Cannot install · 1 Not supported")
  ).toBeInTheDocument();
  expect(
    screen.getAllByText(
      "Connect GitHub to sync more than 20 external repositories."
    )
  ).toHaveLength(1);
  await user.click(
    screen.getByRole("button", { name: /that Onyx cannot use$/ })
  );
  expect(
    screen.getAllByText("Onyx did not read this repository.")
  ).toHaveLength(2);
  expect(
    screen.getByText("Onyx runs only skills and MCP servers.")
  ).toBeInTheDocument();
});
