/**
 * Unit Test: SidebarSection Hover Behavior
 *
 * Tests that the action button in the SidebarSection appears only on hover
 */
import React from "react";
import { render, screen } from "@tests/setup/test-utils";
import { SidebarSection } from "./SidebarSection";
import SvgFolderPlus from "@/icons/folder-plus";
import IconButton from "@/refresh-components/buttons/IconButton";

describe("SidebarSection hover behavior", () => {
  test("action button is hidden by default (opacity-0)", () => {
    render(
      <SidebarSection
        title="Projects"
        action={
          <IconButton
            icon={SvgFolderPlus}
            internal
            tooltip="New Project"
            onClick={() => {}}
            data-testid="new-project-icon"
          />
        }
      >
        <div>Project content</div>
      </SidebarSection>
    );

    const actionButton = screen.getByTestId("new-project-icon");
    const actionContainer = actionButton.closest("div");

    // Check that the action container has opacity-0 class
    expect(actionContainer).toHaveClass("opacity-0");
  });

  test("action button appears on hover (group-hover:opacity-100)", () => {
    render(
      <SidebarSection
        title="Projects"
        action={
          <IconButton
            icon={SvgFolderPlus}
            internal
            tooltip="New Project"
            onClick={() => {}}
            data-testid="new-project-icon"
          />
        }
      >
        <div>Project content</div>
      </SidebarSection>
    );

    const actionButton = screen.getByTestId("new-project-icon");
    const actionContainer = actionButton.closest("div");

    // Verify the container has the hover class that will show it
    expect(actionContainer).toHaveClass("group-hover:opacity-100");
  });

  test("section has group class for hover targeting", () => {
    render(
      <SidebarSection
        title="Projects"
        action={
          <IconButton
            icon={SvgFolderPlus}
            internal
            tooltip="New Project"
            onClick={() => {}}
          />
        }
      >
        <div>Project content</div>
      </SidebarSection>
    );

    // Find the main section container by title
    const titleElement = screen.getByText("Projects");
    const sectionContainer = titleElement.closest("div")?.parentElement;

    // Verify the section has the 'group' class needed for hover
    expect(sectionContainer).toHaveClass("group");
  });

  test("renders without action button when not provided", () => {
    render(
      <SidebarSection title="Projects">
        <div>Project content</div>
      </SidebarSection>
    );

    const titleElement = screen.getByText("Projects");
    expect(titleElement).toBeInTheDocument();

    // Should not render action container when no action is provided
    const headerContainer = titleElement.parentElement;
    const actionContainers = headerContainer?.querySelectorAll(
      ".opacity-0.group-hover\\:opacity-100"
    );
    expect(actionContainers?.length).toBe(0);
  });
});
