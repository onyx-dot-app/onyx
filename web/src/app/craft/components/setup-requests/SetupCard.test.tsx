import {
  act,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import { StrictMode } from "react";
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

  it("waits for the pending request to resolve before showing an existing connection", async () => {
    let complete: () => void = () => {};
    mockPostConnectAppDecision.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          complete = resolve;
        })
    );
    render(
      <StrictMode>
        <SetupCard
          requestId="request-id"
          externalAppId={42}
          reason={null}
          userApp={{ ...userApp, authenticated: true }}
        />
      </StrictMode>
    );

    expect(mockPostConnectAppDecision).toHaveBeenCalledTimes(1);
    expect(mockPostConnectAppDecision).toHaveBeenCalledWith(
      "request-id",
      "connected"
    );
    expect(screen.queryByText("Acme CRM connected.")).not.toBeInTheDocument();
    await act(async () => complete());
    expect(screen.getByText("Acme CRM connected.")).toBeInTheDocument();
  });

  it("resolves an existing connection when app data finishes loading", async () => {
    const { rerender } = render(
      <SetupCard requestId="request-id" externalAppId={42} reason={null} />
    );
    expect(mockPostConnectAppDecision).not.toHaveBeenCalled();
    rerender(
      <SetupCard
        requestId="request-id"
        externalAppId={42}
        reason={null}
        userApp={{ ...userApp, authenticated: true }}
      />
    );
    await waitFor(() =>
      expect(screen.getByText("Acme CRM connected.")).toBeInTheDocument()
    );
    expect(mockPostConnectAppDecision).toHaveBeenCalledTimes(1);
  });

  it("keeps a failed connection decision actionable and retries without new credentials", async () => {
    const user = setupUser();
    mockPostConnectAppDecision.mockRejectedValueOnce(
      new Error("Sandbox unavailable")
    );
    const consoleError = jest
      .spyOn(console, "error")
      .mockImplementation(() => {});
    try {
      render(
        <SetupCard
          requestId="request-id"
          externalAppId={42}
          reason={null}
          userApp={{ ...userApp, authenticated: true }}
        />
      );
      const connect = await screen.findByRole("button", {
        name: "Connect Acme CRM",
      });
      await waitFor(() => expect(connect).toBeEnabled());
      expect(screen.queryByText("Acme CRM connected.")).not.toBeInTheDocument();
      await user.click(connect);
      await waitFor(() =>
        expect(screen.getByText("Acme CRM connected.")).toBeInTheDocument()
      );
      expect(mockPostConnectAppDecision).toHaveBeenCalledTimes(2);
      expect(
        screen.queryByRole("button", { name: "Save credentials" })
      ).not.toBeInTheDocument();
    } finally {
      consoleError.mockRestore();
    }
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
