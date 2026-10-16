/** @jest-environment jsdom */
import { render, screen } from "@tests/setup/test-utils";
import OpenApiActionEditor from "@/sections/actions/OpenApiActionEditor";
import useOpenApiTools from "@/hooks/useOpenApiTools";

jest.mock("@/hooks/useOpenApiTools");
jest.mock("@/sections/actions/OpenApiActionDialogs", () => ({
  __esModule: true,
  default: () => <div role="dialog" aria-label="Editor" />,
}));

it("requires a fresh source snapshot before opening the editor", () => {
  jest.mocked(useOpenApiTools).mockReturnValue({
    openApiTools: [],
    isLoading: false,
    isValidating: true,
    error: undefined,
    mutateOpenApiTools: jest.fn(),
  });
  render(
    <OpenApiActionEditor
      toolId={42}
      name="API"
      onClose={jest.fn()}
      onChanged={jest.fn()}
    />
  );
  expect(useOpenApiTools).toHaveBeenCalledWith({ revalidateOnMount: true });
  expect(
    screen.queryByRole("dialog", { name: "Editor" })
  ).not.toBeInTheDocument();
});

it("reports an unavailable source and keeps the dialog dismissible", () => {
  jest.mocked(useOpenApiTools).mockReturnValue({
    openApiTools: [],
    isLoading: false,
    isValidating: false,
    error: undefined,
    mutateOpenApiTools: jest.fn(),
  });
  render(
    <OpenApiActionEditor
      toolId={42}
      name="API"
      onClose={jest.fn()}
      onChanged={jest.fn()}
    />
  );
  expect(
    screen.getByText(
      "Could not load this OpenAPI action. Close this dialog and try again."
    )
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /close/i })).toBeEnabled();
});
