import {
  DocumentSummary,
  HierarchyItem,
  HierarchySelection,
  HierarchySelectionContext,
  HierarchySelectionState,
} from "@/lib/hierarchy/interfaces";

function buildHierarchy(context: HierarchySelectionContext) {
  const parents = new Map(
    context.nodes.map((node) => [node.id, node.parent_id])
  );
  const children = new Map<number, number[]>();
  for (const node of context.nodes) {
    if (node.parent_id === null) continue;
    const siblings = children.get(node.parent_id) ?? [];
    siblings.push(node.id);
    children.set(node.parent_id, siblings);
  }
  function ancestors(nodeId: number | null): number[] {
    const result: number[] = [];
    while (nodeId !== null && !result.includes(nodeId)) {
      result.push(nodeId);
      nodeId = parents.get(nodeId) ?? null;
    }
    return result;
  }
  return { children, ancestors };
}

export function getHierarchySelectionStates(
  context: HierarchySelectionContext
): Map<number, HierarchySelectionState> {
  const { children, ancestors } = buildHierarchy(context);
  const selectedFolders = new Set(context.selection.folderIds);
  const selectedDocuments = new Set(context.selection.documentIds);
  const partialFolders = new Set<number>();
  for (const id of context.selection.folderIds) {
    ancestors(id).forEach((ancestor) => partialFolders.add(ancestor));
  }
  for (const id of context.selection.documentIds) {
    ancestors(context.documentDetails.get(id)?.parent_id ?? null).forEach(
      (ancestor) => partialFolders.add(ancestor)
    );
  }

  const states = new Map<number, HierarchySelectionState>();
  function getState(id: number): HierarchySelectionState {
    const cached = states.get(id);
    if (cached) return cached;
    if (ancestors(id).some((ancestor) => selectedFolders.has(ancestor))) {
      states.set(id, "checked");
      return "checked";
    }
    states.set(id, "unchecked");
    const childStates = (children.get(id) ?? []).map(getState);
    const files = context.folderDocuments.get(id);
    const allSelected =
      files?.complete &&
      files.documents.length + childStates.length > 0 &&
      files.documents.every((document) => selectedDocuments.has(document.id)) &&
      childStates.every((state) => state === "checked");
    const state = allSelected
      ? "checked"
      : partialFolders.has(id) ||
          childStates.some((child) => child !== "unchecked")
        ? "mixed"
        : "unchecked";
    states.set(id, state);
    return state;
  }
  context.nodes.forEach((node) => getState(node.id));
  return states;
}

// Store fully selected subtrees as folder attachments so they reopen as
// checked even before their files are loaded, without redundant children.
export function compactHierarchySelection(
  context: HierarchySelectionContext
): HierarchySelection {
  const { ancestors } = buildHierarchy(context);
  const states = getHierarchySelectionStates(context);
  const fullFolders = context.nodes
    .filter(
      (node) =>
        states.get(node.id) === "checked" &&
        !ancestors(node.parent_id).some((id) => states.get(id) === "checked")
    )
    .map((node) => node.id);
  const roots = new Set(fullFolders);
  const isCovered = (parentId: number | null) =>
    ancestors(parentId).some((id) => roots.has(id));
  const folderIds = new Set(
    context.selection.folderIds.filter((id) => roots.has(id) || !isCovered(id))
  );
  fullFolders.forEach((id) => folderIds.add(id));
  return {
    folderIds: Array.from(folderIds),
    documentIds: context.selection.documentIds.filter(
      (id) => !isCovered(context.documentDetails.get(id)?.parent_id ?? null)
    ),
  };
}

export async function updateHierarchySelection(
  context: HierarchySelectionContext,
  items: HierarchyItem[],
  selected: boolean,
  loadDocuments: (folderId: number) => Promise<DocumentSummary[]>
): Promise<HierarchySelection> {
  const { children, ancestors } = buildHierarchy(context);
  const folders = new Set(context.selection.folderIds);
  const documents = new Set(context.selection.documentIds);
  const targetFolders = new Set(
    items.filter((item) => item.type === "folder").map((item) => item.data.id)
  );
  const targetDocuments = new Set(
    items.filter((item) => item.type === "document").map((item) => item.data.id)
  );
  const affectedAncestors = new Set<number>();
  items.forEach((item) => {
    ancestors(
      item.type === "folder" ? item.data.id : item.data.parent_id
    ).forEach((id) => affectedAncestors.add(id));
  });
  const isTargetSubtree = (parentId: number | null) =>
    ancestors(parentId).some((id) => targetFolders.has(id));

  // Remove redundant descendants when selecting a whole folder, or clear
  // every descendant when deselecting it. Other sources stay untouched.
  for (const id of context.selection.folderIds) {
    if (isTargetSubtree(id)) folders.delete(id);
  }
  for (const id of context.selection.documentIds) {
    const document = context.documentDetails.get(id);
    if (document && isTargetSubtree(document.parent_id)) documents.delete(id);
  }

  if (selected) {
    targetFolders.forEach((id) => folders.add(id));
    targetDocuments.forEach((id) => documents.add(id));
  } else {
    // Split selected ancestors along the path to the deselected items:
    // keep sibling subtrees as folders, and retain their direct files.
    const retainOtherContents = async (folderId: number): Promise<void> => {
      if (isTargetSubtree(folderId)) return;
      const files = await loadDocuments(folderId);
      files.forEach((document) => {
        if (!targetDocuments.has(document.id)) documents.add(document.id);
      });
      for (const childId of children.get(folderId) ?? []) {
        if (isTargetSubtree(childId)) continue;
        if (affectedAncestors.has(childId)) await retainOtherContents(childId);
        else folders.add(childId);
      }
    };
    for (const id of context.selection.folderIds) {
      if (!affectedAncestors.has(id)) continue;
      folders.delete(id);
      await retainOtherContents(id);
    }
    targetDocuments.forEach((id) => documents.delete(id));
  }

  return { folderIds: Array.from(folders), documentIds: Array.from(documents) };
}
