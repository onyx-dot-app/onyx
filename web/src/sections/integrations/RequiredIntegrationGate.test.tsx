import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { PointerEventsCheckLevel } from "@testing-library/user-event";
import { loadPage } from "@opal/navigation";
import RequiredIntegrationGate from "@/sections/integrations/RequiredIntegrationGate";
import type { MemberIntegration } from "@/lib/integrations/types";
import messages from "@/i18n/messages/en.json";
import { mockFetch } from "@tests/setup/integrationTestUtils";
import {
  makeAccess,
  makeMemberIntegration,
} from "@tests/setup/memberIntegrationTestUtils";

const copy = messages.integrations.requiredGate;
let mockIsAdmin = false;

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    user: { id: "user-1", is_anonymous_user: false },
    isAdmin: mockIsAdmin,
  }),
}));
jest.mock("@opal/navigation", () => ({
  ...jest.requireActual<typeof import("@opal/navigation")>("@opal/navigation"),
  loadPage: jest.fn(),
}));
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ logoUrl: null }),
}));

const required = makeMemberIntegration({
  id: 1,
  name: "Reports API",
  description: "Weekly reports",
  auth_method: "api_key",
  credential_fields: [{ key: "token", label: "Token", secret: true }],
  access: makeAccess({ installation_policy: "REQUIRED" }),
});
const connected: MemberIntegration = {
  ...required,
  status: { state: "connected", reason: null },
  access: makeAccess({ installation_policy: "REQUIRED", state: "on" }),
};

afterEach(() => {
  jest.restoreAllMocks();
  mockIsAdmin = false;
  window.sessionStorage.clear();
});

function progress(connected: number, total: number) {
  return copy.progress
    .replace("{connected}", String(connected))
    .replace("{total}", String(total));
}

test("a member continues only after each required integration connects", async () => {
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  let list = [required];
  mockFetch({
    "/api/integrations": () => list,
    "PUT /api/integrations/1/connection": () => {
      list = [connected];
      return { state: "connected", reason: null };
    },
  });

  render(<RequiredIntegrationGate />);

  const gate = await screen.findByRole("dialog", { name: copy.title });
  const next = within(gate).getByRole("button", { name: copy.continue });
  expect(next).toBeDisabled();
  expect(within(gate).getByText(copy.description)).toBeInTheDocument();
  expect(within(gate).getByText(progress(0, 1))).toBeInTheDocument();

  await user.click(
    within(gate).getByRole("button", { name: "Connect Reports API" })
  );
  const modal = await screen.findByRole("dialog", {
    name: /^Connect Reports API/,
  });
  const token = within(modal).getByLabelText(/Token/);
  await waitFor(() => expect(token).toHaveFocus());
  await user.keyboard("secret{Enter}");

  await waitFor(() => expect(next).toBeEnabled());
  expect(within(gate).getByText(copy.connected)).toBeInTheDocument();
  expect(within(gate).getByText(progress(1, 1))).toBeInTheDocument();
  await waitFor(() => expect(next).toHaveFocus());
  expect(within(gate).getByText("Reports API")).toBeInTheDocument();

  await user.click(next);
  await waitFor(() =>
    expect(
      screen.queryByRole("dialog", { name: copy.title })
    ).not.toBeInTheDocument()
  );
});

test("a row that stops being required without a connection leaves the gate", async () => {
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  const other = makeMemberIntegration({
    id: 2,
    name: "Billing API",
    access: makeAccess({ installation_policy: "REQUIRED" }),
  });
  const nowAvailable: MemberIntegration = {
    ...other,
    access: makeAccess({ installation_policy: "AVAILABLE" }),
  };
  let list = [required, other];
  mockFetch({
    "/api/integrations": () => list,
    "PUT /api/integrations/1/connection": () => {
      list = [connected, nowAvailable];
      return { state: "connected", reason: null };
    },
  });

  render(<RequiredIntegrationGate />);

  const gate = await screen.findByRole("dialog", { name: copy.title });
  expect(within(gate).getByText("Billing API")).toBeInTheDocument();
  await user.click(
    within(gate).getByRole("button", { name: "Connect Reports API" })
  );
  const modal = await screen.findByRole("dialog", {
    name: /^Connect Reports API/,
  });
  await user.type(within(modal).getByLabelText(/Token/), "secret");
  await user.click(within(modal).getByRole("button", { name: "Connect" }));

  const next = within(gate).getByRole("button", { name: copy.continue });
  await waitFor(() => expect(next).toBeEnabled());
  expect(within(gate).queryByText("Billing API")).not.toBeInTheDocument();
  expect(within(gate).getAllByText(copy.connected)).toHaveLength(1);
});

test("an admin continues without connecting, once per browser session", async () => {
  mockIsAdmin = true;
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  const fetchMock = mockFetch({ "/api/integrations": [required] });

  const { unmount } = render(<RequiredIntegrationGate />);

  const gate = await screen.findByRole("dialog", { name: copy.title });
  expect(within(gate).getByText(copy.adminDescription)).toBeInTheDocument();
  expect(within(gate).queryByText(copy.description)).not.toBeInTheDocument();
  await user.click(within(gate).getByRole("button", { name: copy.continue }));
  await waitFor(() =>
    expect(
      screen.queryByRole("dialog", { name: copy.title })
    ).not.toBeInTheDocument()
  );

  unmount();
  const calls = fetchMock.mock.calls.length;
  render(<RequiredIntegrationGate />);
  await waitFor(() =>
    expect(fetchMock.mock.calls.length).toBeGreaterThan(calls)
  );
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("a failed refresh keeps the gate open", async () => {
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  const other = makeMemberIntegration({
    id: 2,
    name: "Billing API",
    access: makeAccess({ installation_policy: "REQUIRED" }),
  });
  let failing = false;
  const fetchMock = mockFetch({
    "/api/integrations": () =>
      failing ? new Response(null, { status: 503 }) : [required, other],
    "PUT /api/integrations/1/connection": () => {
      failing = true;
      return { state: "connected", reason: null };
    },
  });

  render(<RequiredIntegrationGate />);

  const gate = await screen.findByRole("dialog", { name: copy.title });
  await user.click(
    within(gate).getByRole("button", { name: "Connect Reports API" })
  );
  const modal = await screen.findByRole("dialog", {
    name: /^Connect Reports API/,
  });
  await user.type(within(modal).getByLabelText(/Token/), "secret");
  await user.click(within(modal).getByRole("button", { name: "Connect" }));

  await waitFor(() =>
    expect(
      fetchMock.mock.calls.filter(([url]) =>
        String(url).endsWith("/api/integrations")
      ).length
    ).toBeGreaterThan(1)
  );
  expect(screen.getByRole("dialog", { name: copy.title })).toBeInTheDocument();
});

test("a row that needs a reconnect says why", async () => {
  mockFetch({
    "/api/integrations": [
      {
        ...required,
        status: { state: "needs_reconnect", reason: "The key expired." },
      },
    ],
  });

  render(<RequiredIntegrationGate />);

  const gate = await screen.findByRole("dialog", { name: copy.title });
  expect(within(gate).getByText("The key expired.")).toBeInTheDocument();
});

test("nothing renders when no integration blocks the user", async () => {
  const notRequired = makeMemberIntegration({
    id: 2,
    access: makeAccess({ installation_policy: "DEFAULT" }),
  });
  const adminOnly = makeMemberIntegration({
    id: 3,
    auth_mode: "shared",
    access: makeAccess({ installation_policy: "REQUIRED" }),
  });
  const fetchMock = mockFetch({
    "/api/integrations": [notRequired, adminOnly],
  });

  render(<RequiredIntegrationGate />);

  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByText(copy.title)).not.toBeInTheDocument();
});

test("a failed read does not block the user", async () => {
  const fetchMock = mockFetch({
    "/api/integrations": () => new Response(null, { status: 500 }),
  });

  render(<RequiredIntegrationGate />);

  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

test("a member who cannot connect can skip the gate for the browser session", async () => {
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  mockFetch({ "/api/integrations": () => [required] });

  const { unmount } = render(<RequiredIntegrationGate />);

  const gate = await screen.findByRole("dialog", { name: copy.title });
  expect(
    within(gate).queryByRole("button", { name: copy.skip })
  ).not.toBeInTheDocument();

  await user.click(
    within(gate).getByRole("button", { name: "Connect Reports API" })
  );
  await screen.findByRole("dialog", { name: /^Connect Reports API/ });
  await user.keyboard("{Escape}");

  expect(
    await within(gate).findByText(
      copy.askAdmin.replace("{name}", "Reports API")
    )
  ).toBeInTheDocument();
  await user.click(within(gate).getByRole("button", { name: copy.skip }));
  await waitFor(() =>
    expect(
      screen.queryByRole("dialog", { name: copy.title })
    ).not.toBeInTheDocument()
  );

  expect(window.sessionStorage.getItem("onyx:required-gate-dismissed")).toBe(
    "user-1"
  );
  unmount();
  render(<RequiredIntegrationGate />);
  expect(
    screen.queryByRole("dialog", { name: copy.title })
  ).not.toBeInTheDocument();
});

test("a same-tab sign-in that does not connect offers skip on return", async () => {
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  const oauthRequired = makeMemberIntegration({
    id: 2,
    name: "Linear",
    access: makeAccess({ installation_policy: "REQUIRED" }),
  });
  jest.spyOn(window, "open").mockReturnValue(null);
  mockFetch({
    "/api/integrations": () => [oauthRequired],
    "POST /api/integrations/2/oauth/start": () => ({
      authorization_url: "https://provider.example/authorize",
    }),
  });

  const { unmount } = render(<RequiredIntegrationGate />);
  const gate = await screen.findByRole("dialog", { name: copy.title });
  await user.click(
    within(gate).getByRole("button", { name: "Connect Linear" })
  );
  await waitFor(() => expect(loadPage).toHaveBeenCalled());
  unmount();

  render(<RequiredIntegrationGate />);
  const returned = await screen.findByRole("dialog", { name: copy.title });
  expect(
    await within(returned).findByText(copy.askAdmin.replace("{name}", "Linear"))
  ).toBeInTheDocument();
  expect(
    within(returned).getByRole("button", { name: copy.skip })
  ).toBeInTheDocument();
});
