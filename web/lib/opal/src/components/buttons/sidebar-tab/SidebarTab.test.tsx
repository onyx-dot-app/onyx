// SidebarTab reads its fold state from the enclosing sidebar, not from the
// app-wide sidebar state. SidebarTab is also used for page-level tab
// navigation (e.g. the settings page), and those tabs must stay expanded when
// the app sidebar folds.
import { render, screen } from "@tests/setup/test-utils";
import { SidebarTab } from "@opal/components";
import { SidebarLayouts, SidebarStateProvider } from "@opal/layouts";
import { renderSidebarLogo } from "@/lib/sidebar/utils";

jest.mock("@opal/hooks/useScreenSize", () => ({
  __esModule: true,
  default: () => ({ isMobile: false, isSmallScreen: false }),
}));

function FoldedSidebar({ foldable }: { foldable?: boolean }) {
  return (
    <SidebarStateProvider defaultFolded>
      <SidebarLayouts.Root foldable={foldable}>
        <SidebarLayouts.Header renderAppLogo={renderSidebarLogo}>
          <SidebarTab href="/settings">Settings</SidebarTab>
        </SidebarLayouts.Header>
      </SidebarLayouts.Root>
    </SidebarStateProvider>
  );
}

it("collapses the label inside a folded foldable sidebar", () => {
  render(<FoldedSidebar foldable />);
  expect(screen.queryByText("Settings")).not.toBeInTheDocument();
});

it("keeps the label in a non-foldable sidebar, even when app state is folded", () => {
  render(<FoldedSidebar />);
  expect(screen.getByText("Settings")).toBeInTheDocument();
});

it("keeps the label outside a sidebar, even when app state is folded", () => {
  render(
    <SidebarStateProvider defaultFolded>
      <SidebarTab href="/settings">Settings</SidebarTab>
    </SidebarStateProvider>
  );
  expect(screen.getByText("Settings")).toBeInTheDocument();
});

it("still honors an explicit folded prop as an override", () => {
  render(
    <SidebarStateProvider>
      <SidebarTab href="/settings" folded>
        Settings
      </SidebarTab>
    </SidebarStateProvider>
  );
  expect(screen.queryByText("Settings")).not.toBeInTheDocument();
});
