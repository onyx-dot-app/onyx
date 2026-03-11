import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";
import CommandMenu from "./CommandMenu";
import {
  SvgFileText,
  SvgUsers,
  SvgSettings,
  SvgPlus,
  SvgSearch,
  SvgArrowRight,
} from "@opal/icons";

const meta: Meta<typeof CommandMenu> = {
  title: "refresh-components/modals/CommandMenu",
  component: CommandMenu,
  tags: ["autodocs"],
  parameters: {
    layout: "fullscreen",
  },
};

export default meta;
type Story = StoryObj<typeof CommandMenu>;

export const Default: Story = {
  render: () => {
    const [open, setOpen] = useState(true);
    const [search, setSearch] = useState("");

    return (
      <>
        <button onClick={() => setOpen(true)}>Open Command Menu</button>
        <CommandMenu open={open} onOpenChange={setOpen}>
          <CommandMenu.Content>
            <CommandMenu.Header
              placeholder="Type a command or search..."
              value={search}
              onValueChange={setSearch}
              onClose={() => setOpen(false)}
            />
            <CommandMenu.List emptyMessage="No results found.">
              <CommandMenu.Item
                value="documents"
                icon={SvgFileText}
                onSelect={() => alert("Documents")}
              >
                Search Documents
              </CommandMenu.Item>
              <CommandMenu.Item
                value="people"
                icon={SvgUsers}
                onSelect={() => alert("People")}
              >
                Find People
              </CommandMenu.Item>
              <CommandMenu.Item
                value="settings"
                icon={SvgSettings}
                onSelect={() => alert("Settings")}
              >
                Open Settings
              </CommandMenu.Item>
              <CommandMenu.Action
                value="new-chat"
                icon={SvgPlus}
                shortcut="⌘N"
                onSelect={() => alert("New chat")}
              >
                New Chat
              </CommandMenu.Action>
            </CommandMenu.List>
            <CommandMenu.Footer
              leftActions={
                <>
                  <CommandMenu.FooterAction
                    icon={SvgArrowRight}
                    label="Select"
                  />
                  <CommandMenu.FooterAction icon={SvgSearch} label="Search" />
                </>
              }
            />
          </CommandMenu.Content>
        </CommandMenu>
      </>
    );
  },
};

export const WithFilters: Story = {
  render: () => {
    const [open, setOpen] = useState(true);
    const [search, setSearch] = useState("");

    return (
      <>
        <button onClick={() => setOpen(true)}>Open Command Menu</button>
        <CommandMenu open={open} onOpenChange={setOpen}>
          <CommandMenu.Content>
            <CommandMenu.Header
              placeholder="Search within filter..."
              value={search}
              onValueChange={setSearch}
              onClose={() => setOpen(false)}
              filters={[{ id: "docs", label: "Documents", icon: SvgFileText }]}
              onFilterRemove={(id) => alert(`Remove filter: ${id}`)}
            />
            <CommandMenu.List>
              <CommandMenu.Filter
                value="filter-docs"
                icon={SvgFileText}
                isApplied
              >
                Documents
              </CommandMenu.Filter>
              <CommandMenu.Item value="doc-1" onSelect={() => {}}>
                Q3 Financial Report
              </CommandMenu.Item>
              <CommandMenu.Item value="doc-2" onSelect={() => {}}>
                Engineering Roadmap 2025
              </CommandMenu.Item>
              <CommandMenu.Item value="doc-3" onSelect={() => {}}>
                Onboarding Guide
              </CommandMenu.Item>
            </CommandMenu.List>
          </CommandMenu.Content>
        </CommandMenu>
      </>
    );
  },
};

export const EmptyState: Story = {
  render: () => {
    const [open, setOpen] = useState(true);

    return (
      <>
        <button onClick={() => setOpen(true)}>Open Command Menu</button>
        <CommandMenu open={open} onOpenChange={setOpen}>
          <CommandMenu.Content>
            <CommandMenu.Header
              placeholder="Search..."
              onClose={() => setOpen(false)}
            />
            <CommandMenu.List emptyMessage="No commands match your search.">
              <div />
            </CommandMenu.List>
          </CommandMenu.Content>
        </CommandMenu>
      </>
    );
  },
};
