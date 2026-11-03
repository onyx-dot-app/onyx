import { isCCPairRunKind, type CCPairRunKind } from "@/lib/connectors/types";

/** One run by its attempt id, which is unique only within its kind. */
export interface RunRef {
  id: number;
  kind: CCPairRunKind;
}

/** The run a link points the Indexing tab at: `run=<id>` and an optional `run_kind`, an index run when absent. */
export function parseRunParams(params: URLSearchParams): RunRef | null {
  const id = Number(params.get("run"));
  const kind = params.get("run_kind") ?? "indexing";
  if (!Number.isInteger(id) || id <= 0 || !isCCPairRunKind(kind)) return null;
  return { id, kind };
}

/** Points `query` at `run`, or drops the run so a reload does not reopen it. */
export function writeRunParams(
  query: URLSearchParams,
  run: RunRef | null
): void {
  if (run === null) {
    query.delete("run");
    query.delete("run_kind");
    return;
  }
  query.set("run", String(run.id));
  query.set("run_kind", run.kind);
}

/** The connector page's Indexing tab at `run`. */
export function runHref(ccPairId: number, run: RunRef): string {
  const query = new URLSearchParams({ tab: "indexing" });
  writeRunParams(query, run);
  return `/admin/connector/${ccPairId}?${query.toString()}`;
}
