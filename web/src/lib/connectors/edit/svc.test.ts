import { applyConnectorEdit } from "@/lib/connectors/edit/svc";
import type { ConnectorEditApplyRequest } from "@/lib/connectors/edit/types";

const REQUEST: ConnectorEditApplyRequest = {
  plan_id: "plan-1",
  reconciliation: null,
  credential_path: null,
  added_steps: [],
  dropped_steps: [],
};

function respond(status: number, body: object) {
  jest.spyOn(global, "fetch").mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    })
  );
}

afterEach(() => jest.restoreAllMocks());

describe("applyConnectorEdit", () => {
  it("reports a stale plan on 409 EDIT_PLAN_STALE", async () => {
    respond(409, {
      error_code: "EDIT_PLAN_STALE",
      detail: "The connector changed after planning.",
    });

    await expect(applyConnectorEdit(3, REQUEST)).resolves.toEqual({
      kind: "stale",
      detail: "The connector changed after planning.",
    });
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/manage/admin/cc-pair/3/edit/apply",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("reports any other failure as an error", async () => {
    respond(400, {
      error_code: "INVALID_INPUT",
      detail: "Required steps cannot be dropped: prune.",
    });

    await expect(applyConnectorEdit(3, REQUEST)).resolves.toEqual({
      kind: "error",
      detail: "Required steps cannot be dropped: prune.",
    });
  });
});
