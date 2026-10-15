export function includeLtiCourseRoot(
  hierarchyNodeIds: number[],
  ltiCanvasCourseNodeId: number | null
): number[] {
  if (
    ltiCanvasCourseNodeId === null ||
    hierarchyNodeIds.includes(ltiCanvasCourseNodeId)
  ) {
    return hierarchyNodeIds;
  }

  return [ltiCanvasCourseNodeId, ...hierarchyNodeIds];
}

export function getLtiTutorScopeError(
  ltiContextId: string | null,
  ltiCanvasCourseNodeId: number | null
): string | null {
  if (ltiContextId && ltiCanvasCourseNodeId === null) {
    return "Canvas course content is still indexing. Wait for indexing to finish before saving this tutor.";
  }

  return null;
}
