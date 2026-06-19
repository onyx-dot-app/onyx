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

function DemoSidebar() {
  return (
    <div className="h-full w-60 bg-background-neutral-02 border-r border-border-01 p-4 flex flex-col gap-3">
      <div className="h-6 w-24 rounded-04 bg-background-neutral-04" />
      <div className="h-4 w-full rounded-04 bg-background-neutral-03" />
      <div className="h-4 w-3/4 rounded-04 bg-background-neutral-03" />
      <div className="h-4 w-5/6 rounded-04 bg-background-neutral-03" />
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
  return (
    <div className="w-full h-screen">
      <RootLayout.Root>
        <DemoSidebar />
        <RootLayout.App>
          <RootLayout.MainContent>
            <DemoContent label="Main content" />
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
  return (
    <div className="w-full h-screen">
      <RootLayout.Root>
        <DemoSidebar />
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
  return (
    <div className="w-full h-screen">
      <RootLayout.Root>
        <DemoSidebar />
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
          <RootLayout.Footer>
            <div className="h-12 px-4 border-t border-border-01 bg-background-neutral-01 flex items-center gap-3">
              <span className="text-text-03 text-xs">App footer</span>
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
