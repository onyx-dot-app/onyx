import {
  render,
  screen,
  setupUser,
  waitFor,
  deferred,
} from "@tests/setup/test-utils";
import McpServerPolicyModal from "@/app/craft/v1/apps/admin/McpServerPolicyModal";
import { mcpServerFixture } from "@/lib/skills/__fixtures__/picker";
import type { AppActionPoliciesView } from "@/app/craft/v1/apps/action-policies/types";
const mockApp: AppActionPoliciesView = {
  gated_app_id: 7,
  kind: "mcp_server",
  target_id: 10,
  name: "Reports",
  users_can_manage_policies: true,
  enabled: null,
  actions: [],
};
const mockMutate = jest.fn();
let mockIsValidating = false;
jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  __esModule: true,
  default: (
    _key: string,
    _fetcher: unknown,
    options: { onSuccess: (app: AppActionPoliciesView) => void }
  ) => {
    const React = jest.requireActual<typeof import("react")>("react");
    React.useEffect(() => {
      if (!mockIsValidating) options.onSuccess(mockApp);
    }, [mockIsValidating, mockApp.actions, mockApp.users_can_manage_policies]);
    return {
      data: mockApp,
      mutate: mockMutate,
      isValidating: mockIsValidating,
    };
  },
}));
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
  usePathname: () => "/admin/craft/apps",
}));
it("refreshes its permission source before closing after save", async () => {
  const user = setupUser();
  const close = jest.fn();
  const saved = jest.fn();
  const refreshed = deferred<void>();
  mockMutate.mockReturnValue(refreshed.promise);
  const fetchMock = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(new Response(null, { status: 200 }));
  render(
    <McpServerPolicyModal
      server={mcpServerFixture({ id: 10 })}
      onClose={close}
      onSaved={saved}
    />
  );
  await user.click(
    screen.getByRole("switch", { name: "Let users manage approval settings" })
  );
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(mockMutate).toHaveBeenCalledTimes(1));
  expect(close).not.toHaveBeenCalled();
  expect(
    screen.getByRole("switch", { name: "Let users manage approval settings" })
  ).toBeDisabled();
  refreshed.resolve();
  await waitFor(() => expect(close).toHaveBeenCalledTimes(1));
  expect(saved).toHaveBeenCalledTimes(1);
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/build/admin/action-policies/7",
    expect.objectContaining({
      body: JSON.stringify({
        users_can_manage_policies: false,
        action_policies: {},
      }),
    })
  );
  fetchMock.mockRestore();
});

it("waits for fresh workspace settings before showing the editor", () => {
  mockIsValidating = true;
  try {
    const props = {
      server: mcpServerFixture({ id: 10 }),
      onClose: jest.fn(),
      onSaved: jest.fn(),
    };
    const { rerender } = render(<McpServerPolicyModal {...props} />);
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Retry" })
    ).not.toBeInTheDocument();
    mockApp.users_can_manage_policies = false;
    mockIsValidating = false;
    rerender(<McpServerPolicyModal {...props} />);
    expect(screen.getByRole("switch")).not.toBeChecked();
  } finally {
    mockIsValidating = false;
    mockApp.users_can_manage_policies = true;
  }
});
