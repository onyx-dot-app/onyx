import type { ValidSources } from "@/lib/types";
import type { HierarchyNodeSearchSummary } from "@/lib/hierarchy/interfaces";
import type { SearchDocWithContent } from "@/lib/search/interfaces";

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
