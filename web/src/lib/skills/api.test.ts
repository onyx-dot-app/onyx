import { FetchError } from "@/lib/fetcher";
import { previewGitHubSkills } from "@/lib/skills/api";

describe("skills API errors", () => {
  afterEach(() => jest.restoreAllMocks());

  it("preserves the backend error code and actionable detail", async () => {
    jest.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error_code: "RATE_LIMITED",
          detail:
            "GitHub's API rate limit has been reached. Try again in a few minutes.",
        }),
        {
          status: 429,
          headers: { "Content-Type": "application/json" },
        }
      )
    );

    const request = previewGitHubSkills("owner/repository");

    await expect(request).rejects.toMatchObject<Partial<FetchError>>({
      message:
        "GitHub's API rate limit has been reached. Try again in a few minutes.",
      status: 429,
      info: {
        error_code: "RATE_LIMITED",
        detail:
          "GitHub's API rate limit has been reached. Try again in a few minutes.",
      },
    });
  });

  it("logs malformed error responses before using the fallback", async () => {
    const consoleError = jest
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    jest
      .spyOn(global, "fetch")
      .mockResolvedValueOnce(new Response("not json", { status: 502 }));

    await expect(previewGitHubSkills("owner/repository")).rejects.toMatchObject<
      Partial<FetchError>
    >({
      message: "Request failed (502)",
      status: 502,
      info: undefined,
    });
    expect(consoleError).toHaveBeenCalledWith(
      "Failed to parse skills API error response:",
      expect.anything()
    );
  });
});
