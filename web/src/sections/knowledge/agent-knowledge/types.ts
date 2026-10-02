import type { ValidSources } from "@/lib/connectors/types/source";
import type { HierarchyNodeSearchSummary } from "@/lib/hierarchy/types";
import type { SearchDocWithContent } from "@/lib/search/types";

export type KnowledgeView =
  | "main"
  | "add"
  | "document-sets"
  | "sources"
  | "recent";

export interface KnowledgeSearchResults {
  docs: SearchDocWithContent[];
  nodes: HierarchyNodeSearchSummary[];
}

export interface KnowledgeNavState {
  view: KnowledgeView;
  activeSource: ValidSources | undefined;
}
