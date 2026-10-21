/** Precedence of the connector header's status tag. */
import { ConnectorCredentialPairStatus } from "@/lib/connectors/types";
import { ccPairStatusTag } from "@/views/admin/connectors/ConnectorDetailPage/statusTag";

const ACTIVE = ConnectorCredentialPairStatus.ACTIVE;

describe("ccPairStatusTag", () => {
  it("reads failed when the latest run failed once", () => {
    expect(ccPairStatusTag(ACTIVE, false, "failed").labelKey).toBe("failed");
  });

  it("reads failed when the first run failed", () => {
    expect(
      ccPairStatusTag(
        ConnectorCredentialPairStatus.INITIAL_INDEXING,
        false,
        "failed"
      ).labelKey
    ).toBe("failed");
  });

  it("keeps deleting, paused and invalid ahead of a failed run", () => {
    expect(
      ccPairStatusTag(ConnectorCredentialPairStatus.DELETING, false, "failed")
        .labelKey
    ).toBe("deleting");
    expect(
      ccPairStatusTag(ConnectorCredentialPairStatus.PAUSED, false, "failed")
        .labelKey
    ).toBe("paused");
    expect(
      ccPairStatusTag(ConnectorCredentialPairStatus.INVALID, false, "failed")
        .labelKey
    ).toBe("invalid");
  });

  it("reads failed for repeated failures with no live run", () => {
    expect(ccPairStatusTag(ACTIVE, true, "success").labelKey).toBe("failed");
  });

  it("reads indexed when the latest run succeeded", () => {
    expect(ccPairStatusTag(ACTIVE, false, "success").labelKey).toBe("indexed");
  });

  it("reads indexing when a run is live despite repeated failures", () => {
    expect(ccPairStatusTag(ACTIVE, true, "in_progress").labelKey).toBe(
      "indexing"
    );
  });

  it("reads scheduled while the latest run waits in the queue", () => {
    expect(ccPairStatusTag(ACTIVE, false, "not_started").labelKey).toBe(
      "scheduled"
    );
  });
});
