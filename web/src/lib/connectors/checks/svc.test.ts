/** A refused check run start carries the server's reason to the caller. */
import { startDraftCheckRun } from "@/lib/connectors/checks/svc";
import { fetchErrorDetail } from "@/lib/fetcher";
import { ValidSources } from "@/lib/connectors/types/source";

const REQUEST = {
  source: ValidSources.Confluence,
  credential_id: 26,
  access_type: "public" as const,
  draft_key: "draft",
  form_state: {},
  rerun: "none" as const,
};

function respond(status: number, body: string): void {
  global.fetch = jest.fn(async () => new Response(body, { status }));
}

async function startError(): Promise<unknown> {
  return startDraftCheckRun(REQUEST).then(
    () => null,
    (error: unknown) => error
  );
}

it("keeps the server's detail of a refused start", async () => {
  const detail = "Credential 26 is shared with you.";
  respond(403, JSON.stringify({ error_code: "UNAUTHORIZED", detail }));

  expect(fetchErrorDetail(await startError())).toBe(detail);
});

it("has no detail when the body is not JSON", async () => {
  respond(502, "<html>Bad Gateway</html>");

  const error = await startError();
  expect(error).toBeInstanceOf(Error);
  expect(fetchErrorDetail(error)).toBeNull();
});

it("has no detail when the detail is not text", async () => {
  respond(422, JSON.stringify({ detail: [{ msg: "field required" }] }));

  expect(fetchErrorDetail(await startError())).toBeNull();
});
