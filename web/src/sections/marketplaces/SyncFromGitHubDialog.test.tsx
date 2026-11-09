import {
  act,
  copy,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import SyncFromGitHubDialog, {
  type SyncFromGitHubDialogProps,
} from "@/sections/marketplaces/SyncFromGitHubDialog";
import {
  marketplace,
  preview,
} from "@/sections/marketplaces/__fixtures__/marketplace";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useUser } from "@/providers/UserProvider";
import { Permission } from "@/lib/types";

jest.mock("@/providers/UserProvider", () => ({ useUser: jest.fn() }));
const actualUseUser = jest.requireActual<
  typeof import("@/providers/UserProvider")
>("@/providers/UserProvider").useUser;
// Jest omits the dropdown portal CSS used inside modal dialogs.
const dropdownStyle = document.createElement("style");
beforeAll(() => {
  dropdownStyle.textContent = ".opal-dropdown { pointer-events: auto; }";
  document.head.appendChild(dropdownStyle);
});
afterAll(() => dropdownStyle.remove());
let fetchSpy: jest.SpiedFunction<typeof fetch>;
beforeEach(() => {
  jest.mocked(useUser).mockImplementation(actualUseUser);
  fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(
      async (url) =>
        new Response(
          JSON.stringify(
            url === SWR_KEYS.settings
              ? { tier: "business", ee_features_enabled: true }
              : url === SWR_KEYS.enterpriseSettings
                ? {}
                : url === SWR_KEYS.shareableGroups ||
                    url === SWR_KEYS.buildExternalApps
                  ? []
                  : url === `${SWR_KEYS.marketplaces}/preview`
                    ? preview
                    : marketplace
          )
        )
    );
});
afterEach(() => jest.restoreAllMocks());

function mount(props: Partial<SyncFromGitHubDialogProps> = {}) {
  return render(
    <SyncFromGitHubDialog
      open
      onClose={jest.fn()}
      onSyncRequested={jest.fn()}
      {...props}
    />
  );
}

async function fill() {
  const user = setupUser();
  for (const [label, value] of [
    ["Name", "Team tools"],
    ["Repository Owner", "acme"],
    ["Repository Name", "tools"],
    ["Branch, Tag or Commit", "feature/tools"],
    ["Folder (Optional)", "catalog"],
  ]) {
    if (label && value)
      await user.type(screen.getByRole("textbox", { name: label }), value);
  }
  return user;
}

it.each(["returns", "throws", "unmounts"])(
  "keeps accepted creation when the host %s",
  async (host) => {
    const error = new Error("Host refresh failed");
    const report = jest
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    const onSyncRequested = jest.fn(() => {
      if (host === "throws") throw error;
    });
    const view = mount({ onSyncRequested });
    expect(screen.getByRole("button", { name: "Preview" })).toBeDisabled();
    const user = await fill();
    await user.click(screen.getByRole("button", { name: "Preview" }));
    await screen.findByText("alpha");
    const pending = Promise.withResolvers<Response>();
    fetchSpy.mockImplementation(async (url) =>
      url === SWR_KEYS.marketplaces
        ? pending.promise
        : new Response(JSON.stringify(preview))
    );
    await user.click(screen.getByRole("button", { name: "Request sync" }));
    expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(fetchSpy).toHaveBeenCalledWith(
      SWR_KEYS.marketplaces,
      expect.objectContaining({
        body: JSON.stringify({
          provider: "github",
          provider_config: marketplace.provider_config,
          name: "Team tools",
          personal: true,
        }),
      })
    );
    if (host === "unmounts") view.unmount();
    await act(async () =>
      pending.resolve(new Response(JSON.stringify(marketplace)))
    );
    if (host === "unmounts") {
      expect(onSyncRequested).not.toHaveBeenCalled();
      return;
    }
    expect(await screen.findByText("Sync requested")).toBeInTheDocument();
    expect(
      screen.getByText(/Skills will appear after the sync finishes/)
    ).toBeInTheDocument();
    expect(onSyncRequested).toHaveBeenCalledWith(marketplace);
    if (host === "throws")
      expect(report).toHaveBeenCalledWith(expect.any(String), error);
  }
);

it.each([
  [false, "Branch, Tag or Commit"],
  [true, "Folder (Optional)"],
])("invalidates preview after source edits: %s", async (complete, field) => {
  const pending = Promise.withResolvers<Response>();
  mount();
  const user = await fill();
  fetchSpy.mockReturnValue(pending.promise);
  await user.click(screen.getByRole("button", { name: "Preview" }));
  if (complete) {
    await act(async () =>
      pending.resolve(new Response(JSON.stringify(preview)))
    );
    expect(
      await screen.findByRole("button", { name: "Request sync" })
    ).toBeEnabled();
  }
  await user.type(screen.getByRole("textbox", { name: field }), "-changed");
  await act(async () => pending.resolve(new Response(JSON.stringify(preview))));
  expect(screen.queryByText("alpha")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Preview" })).toBeEnabled();
});

it("never puts a closed session's response into a reopened dialog", async () => {
  const pending = Promise.withResolvers<Response>();
  const onClose = jest.fn();
  const props = { onClose, onSyncRequested: jest.fn() };
  const view = mount(props);
  const user = await fill();
  fetchSpy.mockImplementation(async (url) =>
    url === SWR_KEYS.buildExternalApps ? new Response("[]") : pending.promise
  );
  await user.click(screen.getByRole("button", { name: "Preview" }));
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(onClose).toHaveBeenCalledTimes(1);
  view.rerender(<SyncFromGitHubDialog open={false} {...props} />);
  view.rerender(<SyncFromGitHubDialog open {...props} />);
  await act(async () => pending.resolve(new Response(JSON.stringify(preview))));
  expect(screen.getByRole("textbox", { name: "Repository Owner" })).toHaveValue(
    ""
  );
  expect(screen.queryByText("alpha")).not.toBeInTheDocument();
});

it("shows server errors and allows retry", async () => {
  mount();
  const user = await fill();
  fetchSpy.mockResolvedValue(
    new Response(JSON.stringify({ detail: "Repository is private" }), {
      status: 403,
    })
  );
  await user.click(screen.getByRole("button", { name: "Preview" }));
  expect(await screen.findByText("Repository is private")).toBeInTheDocument();
  fetchSpy.mockResolvedValue(new Response(JSON.stringify(preview)));
  await user.click(screen.getByRole("button", { name: "Preview" }));
  expect(await screen.findByText("alpha")).toBeInTheDocument();
});

it("only offers company scope to global holders and creates with atomic access defaults", async () => {
  const props = {
    onClose: jest.fn(),
    onSyncRequested: jest.fn(),
  };
  let global = false;
  jest.mocked(useUser).mockImplementation(() => ({
    ...actualUseUser(),
    permissions: global ? [Permission.MANAGE_SKILLS] : [],
    adminCapabilities: [Permission.MANAGE_SKILLS],
  }));
  const view = mount(props);
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  global = true;
  view.rerender(<SyncFromGitHubDialog open {...props} />);
  const user = await fill();
  await user.click(
    screen.getByRole("checkbox", { name: /Company Marketplace/ })
  );
  global = false;
  view.rerender(<SyncFromGitHubDialog open {...props} />);
  expect(screen.getByRole("button", { name: "Preview" })).toBeDisabled();
  await user.click(
    screen.getByRole("checkbox", { name: /Company Marketplace/ })
  );
  expect(screen.getByRole("button", { name: "Preview" })).toBeEnabled();
  global = true;
  view.rerender(<SyncFromGitHubDialog open {...props} />);
  await user.click(
    screen.getByRole("checkbox", { name: /Company Marketplace/ })
  );
  const policy = screen.getByRole("combobox", {
    name: copy("skills.modals.share.installation.title"),
  });
  await waitFor(() => expect(policy).toBeEnabled());
  await user.click(policy);
  await user.click(screen.getByRole("option", { name: /^Required/ }));
  await user.click(screen.getByRole("button", { name: "Preview" }));
  await screen.findByText("alpha");
  await user.click(screen.getByRole("button", { name: "Request sync" }));
  await waitFor(() => expect(props.onSyncRequested).toHaveBeenCalled());
  const creates = fetchSpy.mock.calls.filter(
    ([url, init]) => url === SWR_KEYS.marketplaces && init?.method === "POST"
  );
  expect(creates).toHaveLength(1);
  expect(JSON.parse(creates[0]?.[1]?.body?.toString() ?? "{}")).toEqual({
    provider: "github",
    provider_config: marketplace.provider_config,
    name: "Team tools",
    personal: false,
    access: {
      public_permission: "VIEWER",
      installation_policy: "REQUIRED",
      group_shares: [],
    },
  });
  expect(fetchSpy.mock.calls.some(([, init]) => init?.method === "PATCH")).toBe(
    false
  );
});

it.each(["keyboard", "header"])(
  "explains ownership and closes once via %s",
  async (method) => {
    const user = setupUser();
    const onClose = jest.fn();
    mount({ onClose });
    expect(
      screen.getByText("Personal marketplaces belong to you.")
    ).toBeInTheDocument();
    if (method === "keyboard") await user.keyboard("{Escape}");
    else await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  }
);

it("resets company defaults when a creation session is reopened", async () => {
  jest.mocked(useUser).mockImplementation(() => ({
    ...actualUseUser(),
    permissions: [Permission.MANAGE_SKILLS],
  }));
  const props = { onClose: jest.fn(), onSyncRequested: jest.fn() };
  const view = mount(props);
  const user = setupUser();
  await user.click(
    screen.getByRole("checkbox", { name: /Company Marketplace/ })
  );
  const label = copy("skills.modals.share.installation.title");
  await waitFor(() =>
    expect(screen.getByRole("combobox", { name: label })).toBeEnabled()
  );
  await user.click(screen.getByRole("combobox", { name: label }));
  await user.click(screen.getByRole("option", { name: /Required/ }));
  expect(screen.getByRole("combobox", { name: label })).toHaveValue("Required");
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  view.rerender(<SyncFromGitHubDialog open={false} {...props} />);
  view.rerender(<SyncFromGitHubDialog open {...props} />);
  expect(
    screen.getByRole("checkbox", { name: /Company Marketplace/ })
  ).not.toBeChecked();
  await user.click(
    screen.getByRole("checkbox", { name: /Company Marketplace/ })
  );
  expect(screen.getByRole("combobox", { name: label })).toHaveValue(
    copy("skills.modals.share.installation.available")
  );
});

it("closes only once when the host throws and dismissal repeats", async () => {
  const onClose = jest.fn(() => {
    throw new Error("Host close failed");
  });
  const errors: unknown[] = [];
  function handleError(event: ErrorEvent) {
    errors.push(event.error);
    event.preventDefault();
  }
  window.addEventListener("error", handleError);
  try {
    mount({ onClose });
    const user = setupUser();
    await user.click(screen.getByRole("button", { name: "Close" }));
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(errors).toHaveLength(1);
  } finally {
    window.removeEventListener("error", handleError);
  }
});
