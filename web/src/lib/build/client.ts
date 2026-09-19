export function getArtifactUrl(sessionId: string, path: string): string {
  return `/api/build/sessions/${sessionId}/artifacts/${path}`;
}
