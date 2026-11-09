import useSWR, { useSWRConfig } from "swr";
import { Button, Text } from "@opal/components";
import {
  act,
  copy,
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import CompanyMarketplaceAccessModal from "@/sections/marketplaces/CompanyMarketplaceAccessModal";
import { marketplace } from "@/sections/marketplaces/__fixtures__/marketplace";
import { getMarketplace, listMarketplaces } from "@/lib/marketplaces/api";
import { marketplaceAccessDraft } from "@/lib/marketplaces/hooks";
import type { Marketplace } from "@/lib/marketplaces/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Permission } from "@/lib/types";

let mockPermissions: string[];
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    permissions: mockPermissions,
    adminCapabilities: [Permission.MANAGE_SKILLS],
  }),
}));
const scope = copy("skills.modals.share.scopeMenu.ariaLabel");
const organization = copy("chat.modals.share.scope.organization.label");
const privateScope = copy("chat.modals.share.scope.invitedOnly.label");
const url = SWR_KEYS.marketplace(marketplace.id);
const company: Marketplace = {
  ...marketplace,
  owner_user_id: null,
  group_shares: [
    { user_group_id: 1, permission: "VIEWER", installation_policy: "REQUIRED" },
    { user_group_id: 99, permission: "EDITOR", installation_policy: "DEFAULT" },
  ],
};
let current: Marketplace;
let fetchSpy: jest.SpiedFunction<typeof fetch>;
function respond(path: Parameters<typeof fetch>[0]) {
  if (path === SWR_KEYS.settings)
    return new Response(
      JSON.stringify({ tier: "business", ee_features_enabled: true })
    );
  if (path === SWR_KEYS.enterpriseSettings) return new Response("{}");
  if (path === SWR_KEYS.shareableGroups)
    return new Response(JSON.stringify([{ id: 1, name: "Engineering" }]));
  if (path === url)
    return new Response(JSON.stringify({ marketplace: current, skills: [] }));
  if (path === SWR_KEYS.marketplaces)
    return new Response(JSON.stringify([current]));
  throw new Error(`Unexpected request: ${path}`);
}
// Jest omits CSS. Restore the dropdown portal's pointer rule inside Radix dialogs.
const dropdownStyle = document.createElement("style");
beforeAll(() => {
  dropdownStyle.textContent = ".opal-dropdown { pointer-events: auto; }";
  document.head.appendChild(dropdownStyle);
});
afterAll(() => dropdownStyle.remove());
beforeEach(() => {
  current = company;
  mockPermissions = [Permission.MANAGE_SKILLS];
  fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (path) => respond(path));
});
afterEach(() => jest.restoreAllMocks());

function CacheObserver() {
  const { data } = useSWR(SWR_KEYS.marketplaces, listMarketplaces);
  useSWR(url, () => getMarketplace(company.id));
  const { mutate } = useSWRConfig();
  return (
    <>
      <Text>{data?.[0]?.name ?? "Loading sources"}</Text>
      <Button
        onClick={() =>
          void mutate(
            (key) => key === url || (Array.isArray(key) && key[0] === url)
          )
        }
      >
        Refresh source
      </Button>
    </>
  );
}
function mount(onSaved = jest.fn(), onClose = jest.fn()) {
  return {
    onSaved,
    onClose,
    ...render(
      <>
        <CacheObserver />
        <CompanyMarketplaceAccessModal
          open
          marketplaceId={company.id}
          onClose={onClose}
          onSaved={onSaved}
        />
      </>
    ),
  };
}
async function ready() {
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save defaults" })).toBeEnabled()
  );
}
async function chooseScope(option: string) {
  const user = setupUser();
  await user.click(screen.getByRole("combobox", { name: scope }));
  await user.click(screen.getByRole("option", { name: option }));
}
function patches() {
  return fetchSpy.mock.calls.filter(([, init]) => init?.method === "PATCH");
}

it("PATCHes complete defaults once, retains group policies, and refreshes both caches only after success", async () => {
  const user = setupUser();
  const { onSaved, onClose } = mount();
  await ready();
  await chooseScope(organization);
  await user.click(screen.getByRole("combobox", { name: "Installation" }));
  await user.click(
    screen.getByRole("option", { name: /^Installed by default/ })
  );
  const pending = Promise.withResolvers<Response>();
  fetchSpy.mockImplementation(async (path, init) =>
    init?.method === "PATCH" ? pending.promise : respond(path)
  );
  const listReads = fetchSpy.mock.calls.filter(
    ([path]) => path === SWR_KEYS.marketplaces
  ).length;
  const detailReads = fetchSpy.mock.calls.filter(
    ([path]) => path === url
  ).length;
  await user.click(screen.getByRole("button", { name: "Save defaults" }));
  await user.click(screen.getByRole("button", { name: "Working…" }));
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  await user.keyboard("{Escape}{Escape}");
  fireEvent.pointerDown(document.body);
  expect(patches()).toHaveLength(1);
  expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  expect(screen.getByRole("combobox", { name: scope })).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "Close" })
  ).not.toBeInTheDocument();
  expect(onClose).not.toHaveBeenCalled();
  expect(onSaved).not.toHaveBeenCalled();
  expect(
    fetchSpy.mock.calls.filter(([path]) => path === SWR_KEYS.marketplaces)
  ).toHaveLength(listReads);
  expect(fetchSpy.mock.calls.filter(([path]) => path === url)).toHaveLength(
    detailReads
  );
  expect(patches()[0]).toEqual([
    `${url}/access`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...marketplaceAccessDraft(company),
        public_permission: "VIEWER",
        installation_policy: "DEFAULT",
      }),
    },
  ]);
  current = {
    ...company,
    name: "Saved source",
    public_permission: "VIEWER",
    installation_policy: "DEFAULT",
  };
  await act(async () => pending.resolve(new Response(JSON.stringify(current))));
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith(current));
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(await screen.findByText("Saved source")).toBeInTheDocument();
  await waitFor(() =>
    expect(fetchSpy.mock.calls.filter(([path]) => path === url)).toHaveLength(
      detailReads + 1
    )
  );
});

it("keeps failed saves and edits visible without refreshing resources, then retries the same draft", async () => {
  const user = setupUser();
  const { onSaved, onClose } = mount();
  await ready();
  await chooseScope(organization);
  const listReads = fetchSpy.mock.calls.filter(
    ([path]) => path === SWR_KEYS.marketplaces
  ).length;
  const detailReads = fetchSpy.mock.calls.filter(
    ([path]) => path === url
  ).length;
  fetchSpy.mockImplementation(async (path, init) =>
    init?.method === "PATCH"
      ? new Response(JSON.stringify({ detail: "Access changed; try again" }), {
          status: 409,
        })
      : respond(path)
  );
  await user.click(screen.getByRole("button", { name: "Save defaults" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Access changed; try again"
  );
  expect(screen.getByRole("combobox", { name: scope })).toHaveValue(
    organization
  );
  expect(screen.getByText("Group #99")).toBeInTheDocument();
  expect(onSaved).not.toHaveBeenCalled();
  expect(onClose).not.toHaveBeenCalled();
  expect(
    fetchSpy.mock.calls.filter(([path]) => path === SWR_KEYS.marketplaces)
  ).toHaveLength(listReads);
  expect(fetchSpy.mock.calls.filter(([path]) => path === url)).toHaveLength(
    detailReads
  );
  await user.click(screen.getByRole("button", { name: "Save defaults" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Access changed; try again"
  );
  expect(patches()).toHaveLength(2);
  expect(patches()[1]?.[1]?.body).toEqual(patches()[0]?.[1]?.body);
});

it("resets edits on close/reopen and waits for fresh defaults before editing", async () => {
  const user = setupUser();
  const props = { marketplaceId: company.id, onClose: jest.fn() };
  const { rerender } = render(
    <CompanyMarketplaceAccessModal {...props} open />
  );
  await ready();
  await chooseScope(organization);
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(props.onClose).toHaveBeenCalledTimes(1);
  rerender(<CompanyMarketplaceAccessModal {...props} open={false} />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  const pending = Promise.withResolvers<Response>();
  fetchSpy.mockImplementation(async (path) =>
    path === url ? pending.promise : respond(path)
  );
  rerender(<CompanyMarketplaceAccessModal {...props} open />);
  expect(
    screen.queryByRole("button", { name: "Save defaults" })
  ).not.toBeInTheDocument();
  await act(async () =>
    pending.resolve(
      new Response(
        JSON.stringify({
          marketplace: { ...company, installation_policy: "REQUIRED" },
          skills: [],
        })
      )
    )
  );
  await ready();
  expect(screen.getByRole("combobox", { name: scope })).toHaveValue(
    privateScope
  );
  expect(screen.getByRole("combobox", { name: "Installation" })).toHaveValue(
    "Required"
  );
});

it("retains edits across refreshes and disables saving during a failed refresh", async () => {
  const user = setupUser();
  mount();
  await ready();
  await chooseScope(organization);
  current = { ...company, installation_policy: "REQUIRED", group_shares: [] };
  // The cache refresh button is outside the modal's focus scope.
  fireEvent.click(screen.getByText("Refresh source"));
  await waitFor(() =>
    expect(fetchSpy.mock.calls.filter(([path]) => path === url)).toHaveLength(4)
  );
  expect(screen.getByRole("combobox", { name: scope })).toHaveValue(
    organization
  );
  expect(screen.getByRole("combobox", { name: "Installation" })).toHaveValue(
    "Available to install"
  );
  expect(screen.getByText("Group #99")).toBeInTheDocument();
  fetchSpy.mockImplementation(async (path) =>
    path === url ? new Response("{}", { status: 503 }) : respond(path)
  );
  fireEvent.click(screen.getByText("Refresh source"));
  expect(
    await screen.findByText(/Could not load marketplace defaults/)
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save defaults" })).toBeDisabled();
  fetchSpy.mockImplementation(async (path) => respond(path));
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  await ready();
  expect(screen.getByRole("combobox", { name: scope })).toHaveValue(
    organization
  );
  expect(screen.getByText("Group #99")).toBeInTheDocument();
});

it("shows initial loading and load failure without allowing a PATCH", async () => {
  const user = setupUser();
  const pending = Promise.withResolvers<Response>();
  fetchSpy.mockImplementation(async (path) =>
    path === url ? pending.promise : respond(path)
  );
  render(
    <CompanyMarketplaceAccessModal
      open
      marketplaceId={company.id}
      onClose={jest.fn()}
    />
  );
  expect(screen.getByText("Loading access settings…")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: "Save defaults" })
  ).not.toBeInTheDocument();
  await act(async () => pending.resolve(new Response("{}", { status: 403 })));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Could not load marketplace defaults"
  );
  fetchSpy.mockImplementation(async (path) => respond(path));
  await user.click(screen.getByRole("button", { name: "Refresh" }));
  await ready();
  expect(patches()).toHaveLength(0);
});

it("refuses personal marketplaces", async () => {
  current = marketplace;
  render(
    <CompanyMarketplaceAccessModal
      open
      marketplaceId={company.id}
      onClose={jest.fn()}
    />
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "only for company marketplaces"
  );
  expect(
    screen.queryByRole("button", { name: "Save defaults" })
  ).not.toBeInTheDocument();
});

it("refuses a scoped manager before reading company defaults", async () => {
  mockPermissions = [];
  render(
    <CompanyMarketplaceAccessModal
      open
      marketplaceId={company.id}
      onClose={jest.fn()}
    />
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Global skill management permission is required"
  );
  expect(fetchSpy).not.toHaveBeenCalled();
});
