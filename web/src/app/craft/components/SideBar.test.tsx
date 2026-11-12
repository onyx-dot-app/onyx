import { NextIntlClientProvider } from "next-intl";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import BuildSidebar from "@/app/craft/components/SideBar";
import { memberPluginMessages } from "@/sections/plugins/__tests__/memberPluginFixtures";

const mockReplace = jest.fn();
const mockAction = jest.fn();
jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  useRouter: () => ({ replace: mockReplace }),
  usePathname: () => "/craft/v1/plugins",
  useSearchParams: () => new URLSearchParams(),
}));
jest.mock("@/app/craft/contexts/BuildContext", () => ({
  useBuildContext: () => ({
    leftSidebarFolded: false,
    setLeftSidebarFolded: jest.fn(),
  }),
}));
jest.mock("@/app/craft/hooks/useBuildSessionStore", () => ({
  useSession: () => null,
  useSessionHistory: () => [],
  useBuildSessionStore: (
    selector: (state: Record<string, typeof mockAction>) => unknown
  ) =>
    selector({
      renameBuildSession: mockAction,
      deleteBuildSession: mockAction,
      refreshSessionHistory: mockAction,
      returnToMainAgent: mockAction,
    }),
}));
jest.mock("@/providers/UnsavedChangesNavigationProvider", () => ({
  useUnsavedChangesNavigation: () => ({
    requestNavigation: (action: () => void) => action(),
  }),
}));
jest.mock("@/lib/sidebar/hooks", () => ({
  useShowLogoWhenFolded: () => false,
}));
jest.mock("@/lib/app/components", () => ({
  ...jest.requireActual("@/lib/app/components"),
  SidebarLogoMark: () => null,
  SidebarWordmark: () => null,
  AccountPopover: () => null,
}));
jest.mock("@/app/craft/components/OpencodeDebugLogs", () => ({
  __esModule: true,
  default: () => null,
}));

test("Craft navigation opens Plugins at the unified route", async () => {
  render(
    <NextIntlClientProvider
      locale="en"
      messages={{
        ...memberPluginMessages,
        craft: {
          ...memberPluginMessages.craft,
          sideBar: {
            ...memberPluginMessages.craft.sideBar,
            plugins: { label: "Plugins" },
          },
        },
      }}
    >
      <BuildSidebar />
    </NextIntlClientProvider>
  );
  await setupUser().click(screen.getByRole("button", { name: /^Plugins$/ }));
  expect(mockReplace).toHaveBeenCalledWith("/craft/v1/plugins");
  expect(
    screen.queryByRole("button", { name: /^Apps$/ })
  ).not.toBeInTheDocument();
});
