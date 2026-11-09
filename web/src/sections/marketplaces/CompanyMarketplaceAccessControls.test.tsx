import { Button } from "@opal/components";
import {
  act,
  copy,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import CompanyMarketplaceAccessControls from "@/sections/marketplaces/CompanyMarketplaceAccessControls";
import {
  DEFAULT_COMPANY_MARKETPLACE_ACCESS,
  marketplaceAccessDraft,
  useCompanyMarketplaceAccess,
  type MarketplaceAccessDraft,
} from "@/lib/marketplaces/hooks";
import { marketplace } from "@/sections/marketplaces/__fixtures__/marketplace";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Permission } from "@/lib/types";

let mockPermissions: string[] = [];
let mockCapabilities: string[] = [];
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    permissions: mockPermissions,
    adminCapabilities: mockCapabilities,
  }),
}));
const scope = copy("skills.modals.share.scopeMenu.ariaLabel");
const orgPermission = copy(
  "skills.modals.share.organizationPermissionMenu.ariaLabel"
);
const organization = copy("chat.modals.share.scope.organization.label");
const privateScope = copy("chat.modals.share.scope.invitedOnly.label");
let fetchSpy: jest.SpiedFunction<typeof fetch>;
let tier: string;
function respond(path: Parameters<typeof fetch>[0]) {
  if (path === SWR_KEYS.settings)
    return new Response(
      JSON.stringify({ tier, ee_features_enabled: tier !== "community" })
    );
  if (path === SWR_KEYS.enterpriseSettings) return new Response("{}");
  if (path === SWR_KEYS.shareableGroups)
    return new Response(
      JSON.stringify([
        { id: 1, name: "Engineering" },
        { id: 2, name: "Support" },
      ])
    );
  throw new Error(`Unexpected request: ${path}`);
}
beforeEach(() => {
  tier = "business";
  mockPermissions = [Permission.MANAGE_SKILLS];
  mockCapabilities = [];
  fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (path) => respond(path));
});
afterEach(() => jest.restoreAllMocks());

function Harness({
  initial = DEFAULT_COMPANY_MARKETPLACE_ACCESS,
  onSubmit,
}: {
  initial?: MarketplaceAccessDraft;
  onSubmit: (draft: MarketplaceAccessDraft) => void;
}) {
  const access = useCompanyMarketplaceAccess(initial);
  return (
    <>
      <CompanyMarketplaceAccessControls access={access} />
      <Button disabled={!access.ready} onClick={() => onSubmit(access.draft)}>
        Submit
      </Button>
    </>
  );
}
async function ready() {
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Submit" })).toBeEnabled()
  );
}
async function chooseMenu(label: string, option: string) {
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: label }));
  await user.click(screen.getByRole("option", { name: option }));
}
const stored = marketplaceAccessDraft({
  ...marketplace,
  group_shares: [
    { user_group_id: 1, permission: "VIEWER", installation_policy: "REQUIRED" },
    { user_group_id: 99, permission: "EDITOR", installation_policy: "DEFAULT" },
  ],
});

it("presents the chosen creation defaults and changes visibility, permissions and installation", async () => {
  const onSubmit = jest.fn();
  const user = setupUser();
  render(<Harness onSubmit={onSubmit} />);
  await ready();
  expect(screen.getByRole("button", { name: scope })).toHaveTextContent(
    organization
  );
  expect(screen.getByRole("combobox", { name: "Installation" })).toHaveValue(
    "Available to install"
  );
  await chooseMenu(scope, privateScope);
  expect(
    screen.queryByRole("button", { name: orgPermission })
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Submit" }));
  expect(onSubmit).toHaveBeenLastCalledWith({
    ...DEFAULT_COMPANY_MARKETPLACE_ACCESS,
    public_permission: null,
  });
  await chooseMenu(scope, organization);
  await chooseMenu(orgPermission, "Can edit");
  for (const [label, policy] of [
    ["Installed by default", "DEFAULT"],
    ["Required", "REQUIRED"],
    ["Available to install", "AVAILABLE"],
  ]) {
    await user.click(screen.getByRole("combobox", { name: "Installation" }));
    await user.click(
      screen.getByRole("option", { name: new RegExp(`^${label}`) })
    );
    await user.click(screen.getByRole("button", { name: "Submit" }));
    expect(onSubmit).toHaveBeenLastCalledWith({
      ...DEFAULT_COMPANY_MARKETPLACE_ACCESS,
      public_permission: "EDITOR",
      installation_policy: policy,
    });
  }
});

it("adds and removes groups while preserving policies on edited and unresolved grants", async () => {
  const onSubmit = jest.fn();
  const user = setupUser();
  render(<Harness initial={stored} onSubmit={onSubmit} />);
  await screen.findByText("Engineering");
  expect(screen.getByText("Group #99")).toBeInTheDocument();
  await chooseMenu("Access for Engineering", "Can edit");
  await user.click(
    screen.getByRole("combobox", { name: "Find a group to add" })
  );
  await user.click(screen.getByRole("option", { name: "Support" }));
  await user.click(screen.getByRole("button", { name: "Submit" }));
  expect(onSubmit).toHaveBeenLastCalledWith({
    ...stored,
    group_shares: [
      { group_id: 1, permission: "EDITOR", installation_policy: "REQUIRED" },
      { group_id: 99, permission: "EDITOR", installation_policy: "DEFAULT" },
      { group_id: 2, permission: "VIEWER", installation_policy: null },
    ],
  });
  await user.click(screen.getByRole("button", { name: "Access for Support" }));
  await user.click(screen.getByRole("option", { name: "Remove Access" }));
  expect(
    screen.queryByRole("group", { name: "Support" })
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Submit" }));
  expect(onSubmit).toHaveBeenLastCalledWith({
    ...stored,
    group_shares: [
      { group_id: 1, permission: "EDITOR", installation_policy: "REQUIRED" },
      { group_id: 99, permission: "EDITOR", installation_policy: "DEFAULT" },
    ],
  });
});

it("retains grants while groups load or fail and can retry their names", async () => {
  const pending = Promise.withResolvers<Response>();
  fetchSpy.mockImplementation(async (path) =>
    path === SWR_KEYS.shareableGroups ? pending.promise : respond(path)
  );
  const onSubmit = jest.fn();
  const user = setupUser();
  render(<Harness initial={stored} onSubmit={onSubmit} />);
  await screen.findByText("Loading groups…");
  expect(screen.getByText("Group #1")).toBeInTheDocument();
  expect(
    screen.getByRole("combobox", { name: "Find a group to add" })
  ).toBeDisabled();
  await act(async () => pending.resolve(new Response("{}", { status: 503 })));
  expect(await screen.findByText(/Could not load groups/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Submit" }));
  expect(onSubmit).toHaveBeenCalledWith(stored);
  fetchSpy.mockImplementation(async (path) => respond(path));
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  expect(await screen.findByText("Engineering")).toBeInTheDocument();
  expect(screen.getByText("Group #99")).toBeInTheDocument();
});

it("does not interpret settings loading or failure as Community or change stored private access", async () => {
  const pending = Promise.withResolvers<Response>();
  fetchSpy.mockImplementation(async (path) =>
    path === SWR_KEYS.settings ? pending.promise : respond(path)
  );
  const onSubmit = jest.fn();
  const user = setupUser();
  render(<Harness initial={stored} onSubmit={onSubmit} />);
  expect(screen.getByText("Loading access settings…")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
  await act(async () => pending.resolve(new Response("{}", { status: 503 })));
  expect(
    await screen.findByText(/Could not load access settings/)
  ).toBeInTheDocument();
  expect(screen.queryByText(/The Free plan/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: scope })).toHaveTextContent(
    privateScope
  );
  fetchSpy.mockImplementation(async (path) => respond(path));
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  await ready();
  await user.click(screen.getByRole("button", { name: "Submit" }));
  expect(onSubmit).toHaveBeenCalledWith(stored);
});

it("restricts Community sharing but permits its installation settings", async () => {
  tier = "community";
  const user = setupUser();
  const onSubmit = jest.fn();
  render(<Harness onSubmit={onSubmit} />);
  await ready();
  expect(screen.getByText(/The Free plan supports/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: scope })).toBeDisabled();
  expect(screen.getByRole("button", { name: orgPermission })).toBeDisabled();
  expect(
    screen.queryByRole("combobox", { name: "Find a group to add" })
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("combobox", { name: "Installation" }));
  await user.click(screen.getByRole("option", { name: /^Required/ }));
  await user.click(screen.getByRole("button", { name: "Submit" }));
  expect(onSubmit).toHaveBeenCalledWith({
    ...DEFAULT_COMPANY_MARKETPLACE_ACCESS,
    installation_policy: "REQUIRED",
  });
});

it("preserves stored private and group access on a Community workspace", async () => {
  tier = "community";
  render(<Harness initial={stored} onSubmit={jest.fn()} />);
  expect(
    await screen.findByText(/These saved defaults require/)
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: scope })).toHaveTextContent(
    privateScope
  );
  expect(screen.getByText("Group #99")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
});

it.each([{ capabilities: [] }, { capabilities: [Permission.MANAGE_SKILLS] }])(
  "denies non-global authority even with scoped capabilities $capabilities",
  async ({ capabilities }) => {
    mockPermissions = [];
    mockCapabilities = capabilities;
    render(<Harness onSubmit={jest.fn()} />);
    expect(
      await screen.findByText(/Global skill management permission/)
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit" })).toBeDisabled();
    expect(screen.getByRole("button", { name: scope })).toBeDisabled();
  }
);
