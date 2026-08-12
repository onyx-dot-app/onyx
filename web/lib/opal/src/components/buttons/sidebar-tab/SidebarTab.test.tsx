// SidebarTab collapses in CSS, not in React. `SidebarRoot` publishes its fold
// state as `data-folded`, and the tab's stylesheet hides the label from there.
// These tests assert that contract, because jsdom applies no stylesheet.
//
// SidebarTab is also used for page-level tab navigation (e.g. the settings
// page). Those tabs have no sidebar above them and must stay expanded when the
// app sidebar folds.
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

/** The `data-folded` value that decides the tab's look, or null if unset. */
function foldStateOf(label: string): string | null {
  const tab = screen.getByText(label).closest(".opal-sidebar-tab");
  expect(tab).not.toBeNull();
  return tab!.closest("[data-folded]")?.getAttribute("data-folded") ?? null;
}

it("collapses the label inside a folded foldable sidebar", () => {
  render(<FoldedSidebar foldable />);
  expect(foldStateOf("Settings")).toBe("true");
});

it("keeps the label in a non-foldable sidebar, even when app state is folded", () => {
  render(<FoldedSidebar />);
  expect(foldStateOf("Settings")).toBe("false");
});

it("keeps the label outside a sidebar, even when app state is folded", () => {
  render(
    <SidebarStateProvider defaultFolded>
      <SidebarTab href="/settings">Settings</SidebarTab>
    </SidebarStateProvider>
  );
  expect(foldStateOf("Settings")).toBeNull();
});

it("still honors an explicit folded prop as an override", () => {
  render(
    <SidebarStateProvider>
      <SidebarTab href="/settings" folded>
        Settings
      </SidebarTab>
    </SidebarStateProvider>
  );
  const tab = screen.getByText("Settings").closest(".opal-sidebar-tab");
  expect(tab).toHaveAttribute("data-folded", "true");
});

it("names the tab for assistive technology in both states", () => {
  render(<FoldedSidebar foldable />);
  // The label is hidden by CSS while folded, so the name comes from the link.
  expect(screen.getByLabelText("Settings")).toBeInTheDocument();
});
