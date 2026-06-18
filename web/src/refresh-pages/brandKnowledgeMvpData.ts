export const MVP_READINESS = {
  generatedAt: "2026-06-18T04:00:10",
  status: "mvp_ready",
  statusLabel: "MVP Ready",
  project: {
    name: "NovaWear KB 优化版",
    id: 1,
    deliveryBaselineName: "novawear-kb-mvp-run-6-20260618",
    deliveryBaselineId: 11,
  },
  import: {
    businessSources: 43,
    evaluationSources: 4,
    evaluationExcludedFromUpload: true,
    uploaded: 43,
    indexed: 43,
    failed: 0,
    rejected: 0,
    zeroChunks: 0,
    chunkCount: 116,
  },
  rag: {
    total: 16,
    autoPass: 16,
    review: 0,
    failed: 0,
    passRate: 1,
    sensitiveRefusalPassed: true,
  },
  agent: {
    total: 18,
    autoPass: 18,
    review: 0,
    explicitFailed: 0,
    passRate: 1,
    cleanProjectFileCount: 43,
    projectEvaluationFileCount: 0,
    hitEvaluationDocs: [] as string[],
  },
  gates: {
    markdownImportClean: true,
    ragGate: true,
    sensitiveRefusalGate: true,
    agentGate: true,
    frontendReportBound: true,
    freshRerun3x: true,
    deliveryBaseline: true,
  },
  roleResults: [
    { role: "设计企划 Agent", result: "6/6", status: "通过" },
    { role: "商品培训 Agent", result: "6/6", status: "通过" },
    { role: "客服售后 Agent", result: "6/6", status: "通过" },
  ],
  reviewItems: [] as Array<{
    id: string;
    title: string;
    severity: string;
    status: string;
    issue: string;
  }>,
  sourceReports: {
    importReport: "kb-import-eval-mvp-run-6-2026-06-18.json",
    ragReport: "kb-import-eval-mvp-run-6-2026-06-18-rag.json",
    agentReport: "agent-role-mvp-fresh-project-11-2026-06-18.json",
    readinessReport: "mvp-readiness-report-2026-06-18-final.json",
  },
} as const;

export const GATE_LABELS = [
  { key: "markdownImportClean", label: "Markdown clean import" },
  { key: "ragGate", label: "RAG gate" },
  { key: "sensitiveRefusalGate", label: "Sensitive refusal" },
  { key: "agentGate", label: "Agent clean gate" },
  { key: "frontendReportBound", label: "Frontend bound" },
  { key: "freshRerun3x", label: "3x fresh rerun" },
  { key: "deliveryBaseline", label: "Delivery baseline" },
] as const;
