import { NextIntlClientProvider } from "next-intl";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import BuildSidebar from "@/app/craft/components/SideBar";
import englishMessages from "@/i18n/messages/en.json";

const mockReplace = jest.fn();
const mockAction = jest.fn();
jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  useRouter: () => ({ replace: mockReplace }),
  usePathname: () => "/craft/v1",
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

test("Craft navigation opens Customize outside Craft", async () => {
  render(
    <NextIntlClientProvider locale="en" messages={englishMessages}>
      <BuildSidebar />
    </NextIntlClientProvider>
  );
  await setupUser().click(screen.getByRole("button", { name: /^Customize$/ }));
  expect(mockReplace).toHaveBeenCalledWith("/app/customize/skills");
  expect(
    screen.queryByRole("button", { name: /^(Skills|Plugins|Apps)$/ })
  ).not.toBeInTheDocument();
});
