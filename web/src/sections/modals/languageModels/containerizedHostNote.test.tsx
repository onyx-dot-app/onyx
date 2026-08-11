/**
 * Every provider under "Self-hosted & Custom" points at a service on the
 * admin's own machine. When Onyx runs in a container, `localhost` does not
 * reach that machine, so the API Base URL field must explain
 * `host.docker.internal`.
 */

import { render, screen } from "@tests/setup/test-utils";
import CustomModal from "@/sections/modals/languageModels/CustomModal";
import LMStudioModal from "@/sections/modals/languageModels/LMStudioModal";
import OllamaModal from "@/sections/modals/languageModels/OllamaModal";
import OpenAICompatibleModal from "@/sections/modals/languageModels/OpenAICompatibleModal";

let isContainerized = false;

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ is_containerized: isContainerized }),
}));

jest.mock("swr", () => {
  const actual = jest.requireActual("swr");
  return {
    ...actual,
    __esModule: true,
    useSWRConfig: () => ({ mutate: jest.fn() }),
    default: () => ({ data: undefined, error: undefined, isLoading: false }),
  };
});

jest.mock("@/hooks/useTierAtLeast", () => ({
  useTierAtLeast: () => false,
}));

const MODALS = [
  { name: "Ollama", Modal: OllamaModal },
  { name: "LM Studio", Modal: LMStudioModal },
  { name: "OpenAI-Compatible", Modal: OpenAICompatibleModal },
  { name: "Custom", Modal: CustomModal },
];

const NOTE = /With Onyx running in a container/;

describe("containerized host note", () => {
  test.each(MODALS)(
    "$name shows the note when containerized",
    async ({ Modal }) => {
      isContainerized = true;
      render(<Modal onOpenChange={jest.fn()} />);

      expect(await screen.findByText(NOTE)).toBeInTheDocument();
      expect(screen.getByText("host.docker.internal")).toBeInTheDocument();
    }
  );

  test.each(MODALS)("$name hides the note otherwise", async ({ Modal }) => {
    isContainerized = false;
    render(<Modal onOpenChange={jest.fn()} />);

    expect(await screen.findByText("API Base URL")).toBeInTheDocument();
    expect(screen.queryByText(NOTE)).not.toBeInTheDocument();
  });
});
