import useSWR from "swr";
import { act, render, screen } from "@tests/setup/test-utils";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { usePATCreation } from "@/views/settings/PATModal";
import type { PAT } from "@/views/settings/types";

const CREATED_TOKEN: PAT = {
  id: 7,
  name: "Gateway",
  token_display: "onyx_pat_****",
  created_at: "2026-11-20T00:00:00Z",
  expires_at: null,
  last_used_at: null,
  scopes: ["use:llm_gateway"],
};

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

/** A token list and a creator that knows nothing about it, as on the 3rd Party Access tab. */
function AccessProbe() {
  const { data: pats } = useSWR<PAT[]>(SWR_KEYS.userPats, errorHandlingFetcher);
  const tokenCreation = usePATCreation({ defaultName: "Gateway" });
  return (
    <>
      <span>
        {pats?.length ? pats.map((pat) => pat.name).join(",") : "none"}
      </span>
      <button onClick={() => void tokenCreation.createPAT()}>create</button>
    </>
  );
}

describe("usePATCreation", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("refreshes every token list after creating a token", async () => {
    let created = false;
    jest.spyOn(global, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "POST") {
        created = true;
        return jsonResponse({ ...CREATED_TOKEN, token: "onyx_pat_created" });
      }
      return jsonResponse(created ? [CREATED_TOKEN] : []);
    });

    render(<AccessProbe />);
    await screen.findByText("none");

    act(() => screen.getByRole("button", { name: "create" }).click());

    expect(await screen.findByText("Gateway")).toBeInTheDocument();
  });
});
