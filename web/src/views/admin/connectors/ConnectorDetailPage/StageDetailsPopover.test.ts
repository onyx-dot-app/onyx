import { createFormatter } from "next-intl";
import type {
  IndexAttemptStage,
  IndexAttemptStageMetric,
  StageScope,
} from "@/lib/types";
import {
  STAGE_BUCKETS,
  barScale,
  formatSeconds,
  summarizeBuckets,
} from "@/views/admin/connectors/ConnectorDetailPage/StageDetailsPopover";

function metric(
  stage: IndexAttemptStage,
  overrides: Partial<IndexAttemptStageMetric> = {},
  scope: StageScope = "BATCH_LEVEL"
): IndexAttemptStageMetric {
  return {
    stage,
    scope,
    event_count: 1,
    total_duration_ms: 0,
    avg_duration_ms: 10,
    std_dev_duration_ms: 1,
    min_duration_ms: 5,
    max_duration_ms: 20,
    time_first_event: null,
    time_last_event: null,
    ...overrides,
  };
}

function timingOf(
  metrics: IndexAttemptStageMetric[],
  bucket: (typeof STAGE_BUCKETS)[number]
) {
  return summarizeBuckets(metrics).find((s) => s.bucket === bucket)?.timing;
}

describe("summarizeBuckets", () => {
  it("always returns the six buckets in pipeline order", () => {
    expect(summarizeBuckets([]).map((s) => s.bucket)).toEqual([
      "fetchSource",
      "batchPreProcessing",
      "chunking",
      "embedding",
      "vectorDbWrite",
      "postProcessing",
    ]);
  });

  it("leaves a bucket with no recorded stages empty", () => {
    const summaries = summarizeBuckets([metric("CONNECTOR_FETCH")]);
    expect(summaries[0]!.timing).toBeDefined();
    expect(summaries.slice(1).every((s) => s.timing === undefined)).toBe(true);
  });

  it("takes the max batch count and sums min, average and max", () => {
    const timing = timingOf(
      [
        metric("DOC_BATCH_STORE", {
          event_count: 3,
          avg_duration_ms: 100,
          min_duration_ms: 50,
          max_duration_ms: 200,
        }),
        metric("QUEUE_WAIT", {
          event_count: 5,
          avg_duration_ms: 400,
          min_duration_ms: 10,
          max_duration_ms: 900,
        }),
      ],
      "batchPreProcessing"
    );
    expect(timing).toMatchObject({
      batchCount: 5,
      avgMs: 500,
      minMs: 60,
      maxMs: 1100,
    });
  });

  it("combines spreads as the root of the summed squares", () => {
    const timing = timingOf(
      [
        metric("POST_INDEX_DB_UPDATE", { std_dev_duration_ms: 3 }),
        metric("FINALIZATION", { std_dev_duration_ms: 4 }),
      ],
      "postProcessing"
    );
    expect(timing?.stdDevMs).toBe(5);
  });

  it("skips null figures instead of treating them as zero", () => {
    const timing = timingOf(
      [
        metric("VECTOR_DB_WRITE", { avg_duration_ms: 30 }),
        metric("ENRICHMENT_PREP", {
          avg_duration_ms: null,
          std_dev_duration_ms: null,
          min_duration_ms: null,
          max_duration_ms: null,
        }),
      ],
      "vectorDbWrite"
    );
    expect(timing).toMatchObject({ avgMs: 30, stdDevMs: 1, maxMs: 20 });
  });

  it("does not add the embedding waits on top of embedding", () => {
    const timing = timingOf(
      [
        metric("EMBEDDING", { avg_duration_ms: 100 }),
        metric("EMBEDDING_RATE_LIMIT_WAIT", {
          avg_duration_ms: 60,
          event_count: 9,
        }),
      ],
      "embedding"
    );
    expect(timing).toMatchObject({ avgMs: 100, batchCount: 1 });
  });

  it("ignores attempt-level and aggregate stages", () => {
    const summaries = summarizeBuckets([
      metric("CONNECTOR_VALIDATION", {}, "ATTEMPT_LEVEL"),
      metric("CHECKPOINT_LOAD", {}, "ATTEMPT_LEVEL"),
      metric("BATCH_TOTAL"),
      metric("BATCH_UNACCOUNTED"),
    ]);
    expect(summaries.every((s) => s.timing === undefined)).toBe(true);
  });
});

describe("barScale", () => {
  it("scales to the largest max across the rows", () => {
    const buckets = summarizeBuckets([
      metric("CONNECTOR_FETCH", { max_duration_ms: 3_600_000 }),
      metric("EMBEDDING", { max_duration_ms: 130 }),
    ]);
    expect(barScale(buckets)).toBe(3_600_000);
  });

  it("ignores a row with no max", () => {
    const buckets = summarizeBuckets([
      metric("CHUNKING", { max_duration_ms: null }),
      metric("EMBEDDING", { max_duration_ms: 40 }),
    ]);
    expect(barScale(buckets)).toBe(40);
  });

  it("is zero with no data", () => {
    expect(barScale(summarizeBuckets([]))).toBe(0);
  });
});

describe("formatSeconds", () => {
  const english = createFormatter({ locale: "en" });

  it("prints seconds with three decimals", () => {
    expect(formatSeconds(english, 9860)).toBe("9.860s");
    expect(formatSeconds(english, 849)).toBe("0.849s");
    expect(formatSeconds(english, 21400)).toBe("21.400s");
  });

  it("follows the viewer's locale", () => {
    expect(formatSeconds(createFormatter({ locale: "de" }), 9860)).toBe(
      "9,860s"
    );
  });

  it("prints a dash when there is no figure", () => {
    expect(formatSeconds(english, null)).toBe("-");
    expect(formatSeconds(english, undefined)).toBe("-");
  });
});
