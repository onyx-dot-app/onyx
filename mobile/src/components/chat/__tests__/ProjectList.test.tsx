import { describe, expect, it, jest } from "@jest/globals";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { ProjectList } from "@/components/chat/ProjectList";
import type { Project } from "@/chat/contracts/projects";

// SidebarTab imports `router` from expo-router at module load; `jest.mock` is
// hoisted above the imports by babel-jest.
jest.mock("expo-router", () => ({ router: { navigate: jest.fn() } }));

function makeProject(
  overrides: Partial<Project> & Pick<Project, "id" | "name">,
): Project {
  return {
    description: null,
    created_at: "2026-01-01T00:00:00Z",
    instructions: null,
    chat_sessions: [],
    ...overrides,
  };
}

describe("ProjectList", () => {
  it("renders each project name", () => {
    render(
      <ProjectList
        projects={[
          makeProject({ id: 1, name: "Roadmap" }),
          makeProject({ id: 2, name: "Onboarding" }),
        ]}
        onSelect={jest.fn()}
      />,
    );

    expect(screen.getByText("Roadmap")).toBeTruthy();
    expect(screen.getByText("Onboarding")).toBeTruthy();
  });

  it("calls onSelect with the project id when a row is pressed", () => {
    const onSelect = jest.fn();
    render(
      <ProjectList
        projects={[makeProject({ id: 7, name: "Pick me" })]}
        onSelect={onSelect}
      />,
    );

    fireEvent.press(screen.getByText("Pick me"));
    expect(onSelect).toHaveBeenCalledWith(7);
  });

  it("shows an empty state when there are no projects", () => {
    render(<ProjectList projects={[]} onSelect={jest.fn()} />);
    expect(screen.getByText("No projects yet.")).toBeTruthy();
  });

  it("suppresses the empty state while loading", () => {
    render(<ProjectList projects={[]} isLoading onSelect={jest.fn()} />);
    expect(screen.queryByText("No projects yet.")).toBeNull();
  });
});
