/**
 * Permission-based redirect tests for the admin ClientLayout.
 *
 * The layout's redirect `useEffect` is the gate that keeps a user without the
 * required permission from rendering an admin page. Future changes to the
 * routing/permission model could silently regress this — these tests guard
 * the contract.
 */
import React from "react";
import { render } from "@tests/setup/test-utils";
import { ApplicationStatus } from "@/interfaces/settings";
import { Permission, User } from "@/lib/types";

const mockRouter = {
  replace: jest.fn() as jest.Mock,
  push: jest.fn() as jest.Mock,
  refresh: jest.fn() as jest.Mock,
};

let mockPathname = "/admin/agents";
const useUserMock = jest.fn();
const useSettingsMock = jest.fn();
const useScreenSizeMock = jest.fn(() => ({ isMobile: false }));
const useSidebarStateMock = jest.fn(() => ({
  folded: false,
  setFolded: jest.fn(),
}));

jest.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  usePathname: () => mockPathname,
}));

// Override the default UserProvider auto-mock from jest.config so we can vary
// `user` and `permissions` per test.
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => useUserMock(),
}));

jest.mock("@/providers/SettingsProvider", () => ({
  useSettingsContext: () => useSettingsMock(),
}));

jest.mock("@/hooks/useScreenSize", () => ({
  __esModule: true,
  default: () => useScreenSizeMock(),
}));

jest.mock("@/layouts/sidebar-layouts", () => ({
  useSidebarState: () => useSidebarStateMock(),
}));

jest.mock("@/sections/sidebar/AdminSidebar", () => ({
  __esModule: true,
  default: () => <div data-testid="admin-sidebar" />,
}));

jest.mock("@opal/components", () => ({
  Button: ({ children, ...rest }: { children?: React.ReactNode }) => (
    <button {...rest}>{children}</button>
  ),
}));

jest.mock("@opal/icons", () => ({
  SvgSidebar: () => <svg />,
}));

import { ClientLayout } from "./ClientLayout";

function setUser(permissions: Permission[]) {
  useUserMock.mockReturnValue({
    user: { id: "u1", email: "u@example.com" } as Partial<User>,
    permissions,
  });
}

function setNoUser() {
  useUserMock.mockReturnValue({
    user: null,
    permissions: [],
  });
}

beforeEach(() => {
  mockRouter.replace.mockReset();
  mockRouter.push.mockReset();
  mockRouter.refresh.mockReset();
  useUserMock.mockReset();
  useSettingsMock.mockReturnValue({
    settings: { application_status: ApplicationStatus.ACTIVE },
  });
  mockPathname = "/admin/agents";
});

describe("ClientLayout — admin permission redirect", () => {
  it("redirects when the user lacks the route's required permission", () => {
    // /admin/agents requires MANAGE_AGENTS — this user only has MANAGE_LLMS.
    mockPathname = "/admin/agents";
    setUser([Permission.MANAGE_LLMS]);

    render(
      <ClientLayout enableCloud={false}>
        <div>page</div>
      </ClientLayout>
    );

    // First permitted admin route in declaration order for a MANAGE_LLMS-only
    // user is /admin/configuration/language-models.
    expect(mockRouter.replace).toHaveBeenCalledTimes(1);
    expect(mockRouter.replace).toHaveBeenCalledWith(
      "/admin/configuration/language-models"
    );
  });

  it("does not redirect when the user holds the exact required permission", () => {
    mockPathname = "/admin/agents";
    setUser([Permission.MANAGE_AGENTS]);

    render(
      <ClientLayout enableCloud={false}>
        <div>page</div>
      </ClientLayout>
    );

    expect(mockRouter.replace).not.toHaveBeenCalled();
  });

  it("does not redirect when the user has FULL_ADMIN_PANEL_ACCESS (override)", () => {
    // FULL_ADMIN_PANEL_ACCESS short-circuits every per-route permission check.
    mockPathname = "/admin/configuration/web-search";
    setUser([Permission.FULL_ADMIN_PANEL_ACCESS]);

    render(
      <ClientLayout enableCloud={false}>
        <div>page</div>
      </ClientLayout>
    );

    expect(mockRouter.replace).not.toHaveBeenCalled();
  });

  it("does not redirect while the user is still loading", () => {
    // Permissions default to [] during load; without the user-loaded guard,
    // the empty array would trigger a spurious redirect on every admin page.
    mockPathname = "/admin/agents";
    setNoUser();

    render(
      <ClientLayout enableCloud={false}>
        <div>page</div>
      </ClientLayout>
    );

    expect(mockRouter.replace).not.toHaveBeenCalled();
  });

  it("redirects to /app when the fallback path matches the current pathname (loop avoidance)", () => {
    // User is logged in but holds NO admin permissions. The fallback returned
    // by getFirstPermittedAdminRoute is the absolute default (/admin/agents).
    // Since the user is already on /admin/agents and lacks MANAGE_AGENTS,
    // redirecting back there would loop — so we redirect to /app instead.
    mockPathname = "/admin/agents";
    setUser([]);

    render(
      <ClientLayout enableCloud={false}>
        <div>page</div>
      </ClientLayout>
    );

    expect(mockRouter.replace).toHaveBeenCalledTimes(1);
    expect(mockRouter.replace).toHaveBeenCalledWith("/app");
  });
});
