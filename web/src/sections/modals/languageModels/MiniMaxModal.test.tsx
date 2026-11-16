import { MINIMAX_ENDPOINT_OPTIONS } from "@/sections/modals/languageModels/MiniMaxModal";

describe("MINIMAX_ENDPOINT_OPTIONS", () => {
  it("covers both regions and API protocols", () => {
    expect(MINIMAX_ENDPOINT_OPTIONS.map((option) => option.value)).toEqual([
      "https://api.minimax.io/anthropic",
      "https://api.minimax.io/v1",
      "https://api.minimaxi.com/anthropic",
      "https://api.minimaxi.com/v1",
    ]);
  });
});
