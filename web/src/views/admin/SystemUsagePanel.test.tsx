import { render, screen, setupUser } from "@tests/setup/test-utils";
import { useSystemUsage } from "@/lib/usage/hooks";
import type { SystemUsageResponse } from "@/lib/usage/systemUsage";
import SystemUsagePanel from "@/views/admin/SystemUsagePanel";

jest.mock("@/lib/usage/hooks", () => ({
  useSystemUsage: jest.fn(),
}));

const mockUseSystemUsage = useSystemUsage as jest.MockedFunction<
  typeof useSystemUsage
>;

beforeAll(() => {
  Element.prototype.scrollIntoView = jest.fn();
  Element.prototype.hasPointerCapture = jest.fn();
  Element.prototype.setPointerCapture = jest.fn();
  Element.prototype.releasePointerCapture = jest.fn();
});

const SYSTEM_USAGE_RESPONSE = {
  start: "2026-09-01",
  end: "2026-09-02",
  categories: [
    {
      category: "image_summarization",
      totals: {
        input_tokens: 100,
        output_tokens: 20,
        cache_read_tokens: 0,
        cache_creation_tokens: 0,
        cost_cents: 200,
      },
      records: [
        {
          attribution: "ATTRIBUTED",
          model: "claude-sonnet",
          flow: "image_summarization",
          provider: "anthropic",
          day: "2026-09-01",
          input_tokens: 100,
          output_tokens: 20,
          cache_read_tokens: 0,
          cache_creation_tokens: 0,
          cost_cents: 200,
        },
      ],
    },
    {
      category: "unattributed",
      totals: {
        input_tokens: 50,
        output_tokens: 10,
        cache_read_tokens: 0,
        cache_creation_tokens: 0,
        cost_cents: 100,
      },
      records: [
        {
          attribution: "UNATTRIBUTED",
          model: "gpt-5",
          flow: "untagged_invoke",
          provider: "openai",
          day: "2026-09-01",
          input_tokens: 50,
          output_tokens: 10,
          cache_read_tokens: 0,
          cache_creation_tokens: 0,
          cost_cents: 100,
        },
      ],
    },
  ],
} satisfies SystemUsageResponse;

function mockLoadedUsage(): void {
  mockUseSystemUsage.mockReturnValue({
    usage: SYSTEM_USAGE_RESPONSE,
    isLoading: false,
    error: undefined,
    refetch: jest.fn(),
  });
}

test("shows system and unattributed spend by category", () => {
  mockLoadedUsage();

  render(<SystemUsagePanel />);

  expect(screen.getByText("System usage")).toBeInTheDocument();
  expect(screen.getByText("Image summarization")).toBeInTheDocument();
  expect(screen.getAllByText("Unattributed").length).toBeGreaterThan(0);
  expect(
    screen.getByRole("columnheader", { name: "Spend" })
  ).toBeInTheDocument();
  expect(screen.queryByText(/@/)).not.toBeInTheDocument();
});

test("preserves filters while a new date range loads", async () => {
  const user = setupUser();
  mockLoadedUsage();
  const { rerender } = render(<SystemUsagePanel />);

  const modelSelect = screen.getAllByRole("combobox")[0]!;
  await user.click(modelSelect);
  const modelOption = await screen.findByRole("option", {
    name: "claude-sonnet",
  });
  await user.click(modelOption);
  expect(modelSelect).toHaveTextContent("claude-sonnet");
  expect(screen.queryByText("$3.00")).not.toBeInTheDocument();

  mockUseSystemUsage.mockReturnValue({
    usage: undefined,
    isLoading: true,
    error: undefined,
    refetch: jest.fn(),
  });
  rerender(<SystemUsagePanel />);

  mockLoadedUsage();
  rerender(<SystemUsagePanel />);

  expect(screen.queryByText("$3.00")).not.toBeInTheDocument();
});
