import { NextIntlClientProvider } from "next-intl";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import BuildSidebar from "@/app/craft/components/SideBar";
import { memberPluginMessages } from "@/sections/plugins/__tests__/memberPluginFixtures";

const mockPush = jest.fn();
const mockAction = jest.fn();
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  usePathname: () => "/craft/v1/plugins",
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
jest.mock("@/lib/sidebar/utils", () => ({
  renderSidebarLogo: () =>
    function Logo() {
      return null;
    },
}));
jest.mock("@/sections/sidebar/AccountPopover", () => ({
  __esModule: true,
  default: () => null,
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
  expect(mockPush).toHaveBeenCalledWith("/craft/v1/plugins");
  expect(
    screen.queryByRole("button", { name: /^Apps$/ })
  ).not.toBeInTheDocument();
});
