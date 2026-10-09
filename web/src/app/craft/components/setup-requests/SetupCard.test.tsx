import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import SetupCard from "@/app/craft/components/setup-requests/SetupCard";
import type { ExternalAppUserResponse } from "@/app/craft/v1/apps/registry";
import { SWR_KEYS } from "@/lib/swr-keys";

const mockMutate = jest.fn();
const mockPostConnectAppDecision = jest.fn();

jest.mock("swr", () => ({
  ...jest.requireActual("swr"),
  useSWRConfig: () => ({ mutate: mockMutate }),
}));

jest.mock("@/app/craft/services/externalAppsService", () => ({
  postConnectAppDecision: (...args: unknown[]) =>
    mockPostConnectAppDecision(...args),
  startExternalAppOAuth: jest.fn(),
  upsertUserCredentials: jest.fn(),
}));

jest.mock("@/app/craft/v1/apps/UserCredentialsModal", () => ({
  __esModule: true,
  default: ({ open, onSaved }: { open: boolean; onSaved: () => void }) =>
    open ? (
      <button type="button" onClick={onSaved}>
        Save credentials
      </button>
    ) : null,
}));

const userApp: ExternalAppUserResponse = {
  id: 42,
  name: "Acme CRM",
  app_type: "CUSTOM",
  credential_keys: ["token"],
  credential_values: {},
  authenticated: false,
  supports_oauth: false,
};

describe("SetupCard", () => {
  beforeEach(() => {
    mockMutate.mockReset();
    mockPostConnectAppDecision.mockReset();
    mockPostConnectAppDecision.mockResolvedValue(undefined);
  });

  it("refreshes app and skill state after credentials are connected", async () => {
    const user = setupUser();
    render(
      <SetupCard
        requestId="request-id"
        externalAppId={42}
        reason={null}
        userApp={userApp}
      />
    );

    await user.click(screen.getByRole("button", { name: "Connect Acme CRM" }));
    await user.click(screen.getByRole("button", { name: "Save credentials" }));

    await waitFor(() =>
      expect(mockPostConnectAppDecision).toHaveBeenCalledWith(
        "request-id",
        "connected"
      )
    );
    expect(mockMutate).toHaveBeenCalledWith(SWR_KEYS.buildExternalApps);
    expect(mockMutate).toHaveBeenCalledWith(SWR_KEYS.userSkills);
  });
});
