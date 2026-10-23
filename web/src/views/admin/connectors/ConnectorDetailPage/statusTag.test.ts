/** Precedence of the connector header's status tag, the status page's buckets as rows and counts show them, and how a run's kind and tag read. */
import {
  type CCPairRun,
  ConnectorCredentialPairStatus,
  INDEXING_CONNECTOR_STATUSES,
} from "@/lib/connectors/types";
import type { IndexAttemptSnapshot, ValidStatuses } from "@/lib/types";
import {
  bucketStatusTag,
  ccPairStatusTag,
  connectorRowStatusTag,
  runKindLabelKey,
  runStatusTag,
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

function indexingRun(status: ValidStatuses, isBackfill: boolean): CCPairRun {
  const attempt: IndexAttemptSnapshot = {
    id: 1,
    status,
    from_beginning: false,
    new_docs_indexed: 0,
    docs_removed_from_index: 0,
    total_docs_indexed: 0,
    error_msg: null,
    error_count: 0,
    open_doc_error_count: 0,
    open_error_count: 0,
    full_exception_trace: null,
    time_started: null,
    time_updated: "2026-01-01T00:00:00Z",
    time_finished: null,
    is_new_model: false,
    is_backfill: isBackfill,
  };
  return {
    kind: "indexing",
    time_created: "2026-01-01T00:00:00Z",
    attempt,
    resolved_at: null,
    superseded: false,
  };
}

describe("backfill runs", () => {
  it("names a backfill attempt apart from regular indexing", () => {
    expect(runKindLabelKey(indexingRun("success", true))).toBe("backfill");
    expect(runKindLabelKey(indexingRun("success", false))).toBe("indexing");
  });

  it("reads backfilling while a backfill runs and backfilled once it succeeds", () => {
    expect(runStatusTag(indexingRun("in_progress", true)).labelKey).toBe(
      "backfilling"
    );
    expect(runStatusTag(indexingRun("success", true)).labelKey).toBe(
      "backfilled"
    );
    expect(runStatusTag(indexingRun("in_progress", false)).labelKey).toBe(
      "indexing"
    );
  });

  it("keeps the shared failed tag for a failed backfill", () => {
    expect(runStatusTag(indexingRun("failed", true)).labelKey).toBe("failed");
  });
});
