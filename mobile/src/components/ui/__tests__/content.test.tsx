import { describe, expect, it, jest } from "@jest/globals";
import { render, screen } from "@testing-library/react-native";

import { Content, ContentAction } from "@/components/ui/content";
import { Text } from "@/components/ui/text";
import SvgFolder from "@/icons/folder";

describe("Content", () => {
  it("renders the headline layout (icon + title + description)", () => {
    render(
      <Content
        icon={SvgFolder}
        title="My Project"
        description="A description"
      />,
    );
    expect(screen.getByText("My Project")).toBeTruthy();
    expect(screen.getByText("A description")).toBeTruthy();
  });

  it("renders the main-ui/section layout", () => {
    render(
      <Content
        sizePreset="main-ui"
        variant="section"
        title="Files"
        description="Chats can access these files."
      />,
    );
    expect(screen.getByText("Files")).toBeTruthy();
    expect(screen.getByText("Chats can access these files.")).toBeTruthy();
  });

  it("renders a custom leading element in place of the icon", () => {
    render(
      <Content leading={<Text>AV</Text>} icon={SvgFolder} title="Deploy" />,
    );
    expect(screen.getByText("AV")).toBeTruthy();
    expect(screen.getByText("Deploy")).toBeTruthy();
  });

  it("throws for a layout that is not ported (body → ContentSm)", () => {
    const spy = jest.spyOn(console, "error").mockImplementation(() => {});
    expect(() =>
      render(<Content sizePreset="main-ui" variant="body" title="x" />),
    ).toThrow();
    spy.mockRestore();
  });
});

describe("ContentAction", () => {
  it("renders rightChildren beside the content", () => {
    render(
      <ContentAction
        sizePreset="main-ui"
        variant="section"
        title="Instructions"
        rightChildren={<Text>Edit</Text>}
      />,
    );
    expect(screen.getByText("Instructions")).toBeTruthy();
    expect(screen.getByText("Edit")).toBeTruthy();
  });
});
