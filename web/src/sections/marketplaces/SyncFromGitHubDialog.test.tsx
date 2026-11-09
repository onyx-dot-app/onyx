import {
  act,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import SyncFromGitHubDialog from "@/sections/marketplaces/SyncFromGitHubDialog";
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
let fetchSpy: jest.SpiedFunction<typeof fetch>;
beforeEach(() => {
  jest.mocked(useUser).mockImplementation(actualUseUser);
  fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(
      async (url) =>
        new Response(
          JSON.stringify(
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

it("previews explicit slash refs and reports requested work, with duplicate submission disabled", async () => {
  const onSyncRequested = jest.fn();
  render(
    <SyncFromGitHubDialog
      open
      onClose={jest.fn()}
      onSyncRequested={onSyncRequested}
    />
  );
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
  await act(async () =>
    pending.resolve(new Response(JSON.stringify(marketplace)))
  );
  expect(await screen.findByText("Sync requested")).toBeInTheDocument();
  expect(
    screen.getByText(/Skills will appear after the sync finishes/)
  ).toBeInTheDocument();
  expect(onSyncRequested).toHaveBeenCalledWith(marketplace);
});

it("invalidates old preview responses when fields change", async () => {
  const pending = Promise.withResolvers<Response>();
  render(
    <SyncFromGitHubDialog
      open
      onClose={jest.fn()}
      onSyncRequested={jest.fn()}
    />
  );
  const user = await fill();
  fetchSpy.mockReturnValue(pending.promise);
  await user.click(screen.getByRole("button", { name: "Preview" }));
  await user.type(
    screen.getByRole("textbox", { name: "Branch, Tag or Commit" }),
    "-changed"
  );
  await act(async () => pending.resolve(new Response(JSON.stringify(preview))));
  expect(screen.queryByText("alpha")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Preview" })).toBeEnabled();
});

it("never puts a closed session's response into a reopened dialog", async () => {
  const pending = Promise.withResolvers<Response>();
  const onClose = jest.fn();
  const props = { onClose, onSyncRequested: jest.fn() };
  const view = render(<SyncFromGitHubDialog open {...props} />);
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
  render(
    <SyncFromGitHubDialog
      open
      onClose={jest.fn()}
      onSyncRequested={jest.fn()}
    />
  );
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

it("only offers company scope to global holders with an atomic host creator", async () => {
  const create = jest
    .fn()
    .mockResolvedValue({ ...marketplace, owner_user_id: null });
  const props = {
    onClose: jest.fn(),
    onSyncRequested: jest.fn(),
    company: { create, ready: true, controls: null },
  };
  let global = false;
  jest.mocked(useUser).mockImplementation(() => ({
    ...actualUseUser(),
    permissions: global ? [Permission.MANAGE_SKILLS] : [],
    adminCapabilities: [Permission.MANAGE_SKILLS],
  }));
  const view = render(<SyncFromGitHubDialog open {...props} />);
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
  await user.click(screen.getByRole("button", { name: "Preview" }));
  await screen.findByText("alpha");
  await user.click(screen.getByRole("button", { name: "Request sync" }));
  await waitFor(() =>
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ personal: false })
    )
  );
  expect(
    fetchSpy.mock.calls.filter(
      ([url, init]) => url === SWR_KEYS.marketplaces && init?.method === "POST"
    )
  ).toHaveLength(0);
});

it("explains personal ownership and supports keyboard dismissal", async () => {
  const user = setupUser();
  const onClose = jest.fn();
  render(
    <SyncFromGitHubDialog open onClose={onClose} onSyncRequested={jest.fn()} />
  );
  expect(
    screen.getByText("Personal marketplaces belong to you.")
  ).toBeInTheDocument();
  await user.keyboard("{Escape}");
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("invalidates a completed preview after source edits", async () => {
  render(
    <SyncFromGitHubDialog
      open
      onClose={jest.fn()}
      onSyncRequested={jest.fn()}
    />
  );
  const user = await fill();
  await user.click(screen.getByRole("button", { name: "Preview" }));
  expect(
    await screen.findByRole("button", { name: "Request sync" })
  ).toBeEnabled();
  await user.type(
    screen.getByRole("textbox", { name: "Folder (Optional)" }),
    "/changed"
  );
  expect(screen.queryByText("alpha")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Preview" })).toBeEnabled();
});
