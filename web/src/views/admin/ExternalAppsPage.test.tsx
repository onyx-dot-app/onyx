/**
 * @jest-environment jsdom
 */

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@tests/setup/test-utils";
import useSWR from "swr";
import ExternalAppsPage from "@/views/admin/ExternalAppsPage";
import { SWR_KEYS } from "@/lib/swr-keys";
import { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";
import * as externalAppsService from "@/app/craft/services/externalAppsService";

jest.mock("swr", () => ({
  __esModule: true,
  ...jest.requireActual("swr"),
  default: jest.fn(),
}));

jest.mock("@/app/craft/services/externalAppsService");

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
}));

const mockUseSWR = useSWR as jest.MockedFunction<typeof useSWR>;
const mockMutateApps = jest.fn();

const APP: ExternalAppAdminResponse = {
  id: 1,
  name: "Custom app",
  app_type: "CUSTOM",
  upstream_url_patterns: [],
  auth_template: {},
  organization_credentials: {},
  enabled: true,
  actions: [],
  associated_skills: [],
  is_onyx_managed: false,
};

describe("ExternalAppsPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseSWR.mockImplementation((key) => {
      if (key === SWR_KEYS.buildExternalAppsAdmin) {
        return {
          data: [APP],
          error: undefined,
          isLoading: false,
          isValidating: false,
          mutate: mockMutateApps,
        } as ReturnType<typeof useSWR>;
      }
      return {
        data: [],
        error: undefined,
        isLoading: false,
        isValidating: false,
        mutate: jest.fn(),
      } as ReturnType<typeof useSWR>;
    });
    jest.mocked(externalAppsService.updateExternalApp).mockResolvedValue(APP);
  });

  it("keeps app controls disabled until the refreshed app state arrives", async () => {
    let finishRefresh: (() => void) | undefined;
    mockMutateApps.mockReturnValue(
      new Promise<void>((resolve) => {
        finishRefresh = resolve;
      })
    );

    render(<ExternalAppsPage />);
    fireEvent.click(screen.getByRole("button", { name: "Disable" }));

    await waitFor(() => {
      expect(externalAppsService.updateExternalApp).toHaveBeenCalledWith(1, {
        enabled: false,
      });
    });
    expect(screen.getByRole("button", { name: "Disable" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Edit" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Delete Custom app" })
    ).toBeDisabled();

    await act(async () => finishRefresh?.());

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Disable" })).toBeEnabled();
    });
  });
});
