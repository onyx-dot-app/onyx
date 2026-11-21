import type { Tier } from "@/lib/tiers/types";

// Mirrors backend `TokenResponse`.
export interface PAT {
  id: number;
  name: string;
  token_display: string;
  created_at: string;
  expires_at: string | null;
  last_used_at: string | null;
  scopes: string[] | null;
}

// Mirrors backend `CreatedTokenResponse`.
export interface CreatedPAT extends PAT {
  token: string;
}

// Mirrors backend `PatScopeOption`.
export interface PatScopeOption {
  scope: string;
  group_label: string;
  label: string;
  description: string;
  min_tier: Tier;
  implies: string[];
}

export type AccessMode = "full" | "limited";
