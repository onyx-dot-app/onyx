import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react";
import * as RootLayout from "@opal/layouts/root/components";

const meta: Meta = {
  title: "Layouts/RootLayout",
  tags: ["autodocs"],
  parameters: { layout: "fullscreen" },
};

export default meta;
type Story = StoryObj;

// ---------------------------------------------------------------------------
// Shared demo helpers
// ---------------------------------------------------------------------------

function DemoSidebar({ folded }: { folded: boolean }) {
  return (
    <div className="h-full w-60 bg-background-neutral-02 border-r border-border-01 p-4 flex flex-col gap-3">
      {!folded && (
        <>
          <div className="h-6 w-24 rounded-04 bg-background-neutral-04" />
          <div className="h-4 w-full rounded-04 bg-background-neutral-03" />
          <div className="h-4 w-3/4 rounded-04 bg-background-neutral-03" />
          <div className="h-4 w-5/6 rounded-04 bg-background-neutral-03" />
        </>
      )}
    </div>
  );
}

function DemoContent({ label }: { label: string }) {
  return (
    <div className="h-full flex items-center justify-center">
      <span className="text-text-03 text-sm">{label}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stories
// ---------------------------------------------------------------------------

function BasicDemo() {
  const [folded, setFolded] = useState(false);
  return (
    <div className="w-full h-screen">
      <RootLayout.Root>
        <RootLayout.Sidebar
          folded={folded}
          onFoldToggle={() => setFolded((p) => !p)}
        >
          <DemoSidebar folded={folded} />
        </RootLayout.Sidebar>
        <RootLayout.App>
          <RootLayout.MainContent>
            <div className="h-full flex flex-col items-center justify-center gap-3">
              <DemoContent label="Main content" />
              <button
                className="px-3 py-1.5 rounded-08 bg-background-neutral-03 text-text-02 text-sm"
                onClick={() => setFolded((p) => !p)}
              >
                Toggle sidebar
              </button>
            </div>
          </RootLayout.MainContent>
        </RootLayout.App>
      </RootLayout.Root>
    </div>
  );
}

export const Basic: Story = {
  render: () => <BasicDemo />,
};

function WithPanelsDemo() {
  const [folded, setFolded] = useState(false);
  return (
    <div className="w-full h-screen">
      <RootLayout.Root>
        <RootLayout.Sidebar
          folded={folded}
          onFoldToggle={() => setFolded((p) => !p)}
        >
          <DemoSidebar folded={folded} />
        </RootLayout.Sidebar>
        <RootLayout.LeftPanel className="w-56 bg-background-neutral-02 border-r border-border-01">
          <DemoContent label="Left panel" />
        </RootLayout.LeftPanel>
        <RootLayout.App>
          <RootLayout.MainContent>
            <DemoContent label="Main content" />
          </RootLayout.MainContent>
        </RootLayout.App>
        <RootLayout.RightPanel className="w-72 bg-background-neutral-02 border-l border-border-01">
          <DemoContent label="Right panel" />
        </RootLayout.RightPanel>
      </RootLayout.Root>
    </div>
  );
}

export const WithPanels: Story = {
  render: () => <WithPanelsDemo />,
};

function WithHeaderFooterDemo() {
  const [folded, setFolded] = useState(false);
  const [extraPadding, setExtraPadding] = useState(false);
  return (
    <div className="w-full h-screen">
      <RootLayout.Root>
        <RootLayout.Sidebar
          folded={folded}
          onFoldToggle={() => setFolded((p) => !p)}
        >
          <DemoSidebar folded={folded} />
        </RootLayout.Sidebar>
        <RootLayout.App>
          <RootLayout.Header>
            <div className="h-12 px-4 border-b border-border-01 bg-background-neutral-01 flex items-center">
              <span className="text-text-02 text-sm font-medium">
                App header
              </span>
            </div>
          </RootLayout.Header>
          <RootLayout.MainContent>
            <DemoContent label="Scrollable page content" />
          </RootLayout.MainContent>
          <RootLayout.Footer extraPadding={extraPadding}>
            <div className="h-12 px-4 border-t border-border-01 bg-background-neutral-01 flex items-center gap-3">
              <span className="text-text-03 text-xs">App footer</span>
              <button
                className="px-2 py-1 rounded-04 bg-background-neutral-03 text-text-02 text-xs"
                onClick={() => setExtraPadding((p) => !p)}
              >
                extraPadding: {extraPadding ? "on" : "off"}
              </button>
            </div>
          </RootLayout.Footer>
        </RootLayout.App>
      </RootLayout.Root>
    </div>
  );
}

export const WithHeaderFooter: Story = {
  render: () => <WithHeaderFooterDemo />,
};
