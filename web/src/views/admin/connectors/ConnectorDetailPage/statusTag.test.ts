/** Precedence of the connector header's status tag, and the status page's buckets as rows and counts show them. */
import {
  ConnectorCredentialPairStatus,
  INDEXING_CONNECTOR_STATUSES,
} from "@/lib/connectors/types";
import {
  bucketStatusTag,
  ccPairStatusTag,
  connectorRowStatusTag,
} from "@/views/admin/connectors/ConnectorDetailPage/statusTag";

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

describe("status page buckets", () => {
  it("gives every bucket the tag of the same name", () => {
    for (const status of INDEXING_CONNECTOR_STATUSES) {
      expect(bucketStatusTag(status).labelKey).toBe(status);
    }
  });

  it("reads deleting for a row in the deleting bucket", () => {
    expect(
      connectorRowStatusTag(
        ConnectorCredentialPairStatus.DELETING,
        "deleting",
        "failed"
      ).labelKey
    ).toBe("deleting");
  });

  it("reads invalid for an invalid pair in the failed bucket", () => {
    expect(
      connectorRowStatusTag(
        ConnectorCredentialPairStatus.INVALID,
        "failed",
        "success"
      ).labelKey
    ).toBe("invalid");
  });
});
