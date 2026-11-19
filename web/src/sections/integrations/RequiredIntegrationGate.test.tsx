import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { PointerEventsCheckLevel } from "@testing-library/user-event";
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
});

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
  expect(within(gate).getByText(copy.requiredNote)).toBeInTheDocument();
  expect(within(gate).queryByText(copy.adminNote)).not.toBeInTheDocument();

  await user.click(
    within(gate).getByRole("button", { name: "Connect Reports API" })
  );
  const modal = await screen.findByRole("dialog", {
    name: /^Connect Reports API/,
  });
  await user.type(within(modal).getByLabelText(/Token/), "secret");
  await user.click(within(modal).getByRole("button", { name: "Connect" }));

  await waitFor(() => expect(next).toBeEnabled());
  // The row stays and shows that it connected.
  expect(within(gate).getByText(copy.connected)).toBeInTheDocument();
  expect(within(gate).getByText("Reports API")).toBeInTheDocument();

  await user.click(next);
  await waitFor(() =>
    expect(
      screen.queryByRole("dialog", { name: copy.title })
    ).not.toBeInTheDocument()
  );
});

test("an admin can continue without connecting", async () => {
  mockIsAdmin = true;
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  mockFetch({ "/api/integrations": [required] });

  render(<RequiredIntegrationGate />);

  const gate = await screen.findByRole("dialog", { name: copy.title });
  expect(within(gate).getByText(copy.adminNote)).toBeInTheDocument();
  await user.click(within(gate).getByRole("button", { name: copy.continue }));
  await waitFor(() =>
    expect(
      screen.queryByRole("dialog", { name: copy.title })
    ).not.toBeInTheDocument()
  );
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
