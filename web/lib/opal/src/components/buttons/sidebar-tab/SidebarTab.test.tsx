// SidebarTab collapses in CSS, not in React. `SidebarRoot` publishes its fold
// state as `data-folded`, and the tab's stylesheet hides the label from there.
// These tests assert that contract, because jsdom applies no stylesheet.
//
// SidebarTab is also used for page-level tab navigation (e.g. the settings
// page). Those tabs have no sidebar above them and must stay expanded when the
// app sidebar folds.
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { render, screen, userEvent, waitFor } from "@tests/setup/test-utils";
import { SidebarTab } from "@opal/components";
import {
  SidebarLayouts,
  SidebarStateProvider,
  useSidebarState,
} from "@opal/layouts";
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

it("does not show the folded tooltip for a tab the pointer already left", async () => {
  const user = userEvent.setup();

  function FoldableSidebar() {
    const { setFolded } = useSidebarState();
    return (
      <SidebarLayouts.Root foldable>
        <SidebarLayouts.Header renderAppLogo={renderSidebarLogo}>
          <SidebarTab href="/settings">Settings</SidebarTab>
        </SidebarLayouts.Header>
        <button onClick={() => setFolded(true)}>Fold</button>
      </SidebarLayouts.Root>
    );
  }

  render(
    // Open on the first hover, so the test does not wait out the default delay.
    <TooltipPrimitive.Provider delayDuration={0}>
      <SidebarStateProvider>
        <FoldableSidebar />
      </SidebarStateProvider>
    </TooltipPrimitive.Provider>
  );

  // Hover the tab while the sidebar is open, then leave it. An open sidebar
  // shows its labels, so the tooltip stays closed the whole time.
  const tab = screen.getByLabelText("Settings");
  await user.hover(tab);
  await user.unhover(tab);

  await user.click(screen.getByRole("button", { name: "Fold" }));

  // The pointer is elsewhere, so folding must not reveal a tooltip.
  await waitFor(() => {
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});

it("names the tab for assistive technology in both states", () => {
  render(<FoldedSidebar foldable />);
  // The label is hidden by CSS while folded, so the name comes from the link.
  expect(screen.getByLabelText("Settings")).toBeInTheDocument();
});

it("keeps the same DOM node when children switch from a label to an element", () => {
  // An inline rename swaps the string label for an input and drops `href`.
  // A remount here would unmount that input before it could take focus.
  const { rerender } = render(
    <SidebarTab href="/app?chatId=1" onClick={() => {}}>
      My chat
    </SidebarTab>
  );
  const before = screen.getByText("My chat").closest(".opal-sidebar-tab");
  expect(before).not.toBeNull();

  rerender(
    <SidebarTab>
      <input aria-label="Rename chat" defaultValue="My chat" />
    </SidebarTab>
  );
  const after = screen
    .getByRole("textbox", { name: "Rename chat" })
    .closest(".opal-sidebar-tab");
  expect(after).toBe(before);
});

it("shows the folded label tooltip from the tab's control", async () => {
  const user = userEvent.setup();
  render(
    <TooltipPrimitive.Provider delayDuration={0}>
      <FoldedSidebar foldable />
    </TooltipPrimitive.Provider>
  );
  await user.hover(screen.getByLabelText("Settings"));
  await waitFor(() => {
    expect(screen.getByRole("tooltip")).toHaveTextContent("Settings");
  });
});

it("shows an explicit tooltip on a disabled tab", async () => {
  // A disabled tab has no control, so an inert overlay is the trigger.
  const user = userEvent.setup();
  render(
    <TooltipPrimitive.Provider delayDuration={0}>
      <SidebarTab disabled tooltip="Enterprise only">
        Groups
      </SidebarTab>
    </TooltipPrimitive.Provider>
  );
  const tab = screen.getByText("Groups").closest(".opal-sidebar-tab")!;
  const overlay = tab.querySelector('[aria-hidden="true"].inset-0');
  expect(overlay).not.toBeNull();
  // Disabled is `aria-disabled` on a div, never a native disabled control:
  // browsers drop pointer events inside one, which would mute the trigger.
  expect(tab.querySelector("button[disabled]")).toBeNull();
  await user.hover(overlay!);
  await waitFor(() => {
    expect(screen.getByRole("tooltip")).toHaveTextContent("Enterprise only");
  });
});
