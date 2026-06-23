import useSWR from "swr";

export interface GlomiForgeSessionView {
  session_id: string;
  status: string;
  preview_url: string | null;
  latest_output: Record<string, unknown> | null;
  last_error: Record<string, unknown> | null;
}

const TERMINAL_STATUSES = new Set(["completed", "failed", "terminated"]);

export async function fetchGlomiForgeSession(
  url: string
): Promise<GlomiForgeSessionView> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Failed to load Glomi Forge session: ${response.status}`);
  }
  return response.json();
}

export function useGlomiForgeSession(sessionId: string | null) {
  const { data, error, isLoading } = useSWR<GlomiForgeSessionView>(
    sessionId ? `/api/glomi-forge/sessions/${sessionId}` : null,
    fetchGlomiForgeSession,
    {
      refreshInterval: (session) =>
        session && TERMINAL_STATUSES.has(session.status) ? 0 : 2000,
    }
  );

  return { session: data, error, isLoading };
}
