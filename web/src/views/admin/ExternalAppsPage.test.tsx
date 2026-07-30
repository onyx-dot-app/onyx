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
  useRouter: () => ({ push: jest.fn(), replace: mockRouterReplace }),
  useSearchParams: () => mockSearchParams,
  usePathname: () => "/admin/craft/apps",
}));

const mockUseSWR = useSWR as jest.MockedFunction<typeof useSWR>;
const mockMutateApps = jest.fn();
const mockRouterReplace = jest.fn();
let mockSearchParams = new URLSearchParams();

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
    mockSearchParams = new URLSearchParams();
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

  it("confirms retained skill behavior before deleting an app", async () => {
    mockUseSWR.mockImplementation((key) => {
      if (key === SWR_KEYS.buildExternalAppsAdmin) {
        return {
          data: [
            {
              ...APP,
              name: "Slack",
              app_type: "SLACK",
              associated_skills: [
                { id: "skill-a", name: "acme-lookup", is_valid: true },
                { id: "skill-b", name: "acme-write", is_valid: true },
              ],
            },
          ],
          mutate: mockMutateApps,
          error: undefined,
          isLoading: false,
          isValidating: false,
        } as ReturnType<typeof useSWR>;
      }
      return {
        data: [],
        mutate: jest.fn(),
        error: undefined,
        isLoading: false,
        isValidating: false,
      } as ReturnType<typeof useSWR>;
    });
    jest.mocked(externalAppsService.deleteExternalApp).mockResolvedValue();
    mockMutateApps.mockResolvedValue(undefined);

    render(<ExternalAppsPage />);
    fireEvent.click(screen.getByRole("button", { name: "Delete Slack" }));

    expect(screen.getByRole("dialog")).toHaveTextContent(
      "This deletes the app configuration, connection data, and any provider-managed skills."
    );
    expect(
      screen.getByText(
        "2 associated custom skills will be kept, unlinked from this app, and disabled for everyone."
      )
    ).toBeInTheDocument();
    expect(externalAppsService.deleteExternalApp).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Delete app" }));
    await waitFor(() =>
      expect(externalAppsService.deleteExternalApp).toHaveBeenCalledWith(1)
    );
  });

  it("keeps deep-linked app settings open during revalidation", async () => {
    mockSearchParams = new URLSearchParams({ editAppId: "1" });
    let isValidating = false;
    mockUseSWR.mockImplementation((key) => {
      if (key === SWR_KEYS.buildExternalAppsAdmin) {
        return {
          data: [APP],
          error: undefined,
          isLoading: false,
          isValidating,
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

    const { rerender } = render(<ExternalAppsPage />);

    expect(await screen.findByText("Edit Custom app")).toBeInTheDocument();
    expect(mockRouterReplace).not.toHaveBeenCalled();

    isValidating = true;
    rerender(<ExternalAppsPage />);
    expect(screen.getByText("Edit Custom app")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(mockRouterReplace).toHaveBeenCalledWith("/admin/craft/apps");
  });
});
