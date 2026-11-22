/**
 * Per-user skill limits: the 413 a refused write returns, the skills a
 * session left out, and the users past the write limit.
 *
 * Pairs with `backend/onyx/skills/limits.py` and `backend/onyx/db/skill_limit.py`.
 */

import { FetchError } from "@/lib/fetcher";

export const SKILL_LIMIT_EXCEEDED = "SKILL_LIMIT_EXCEEDED";

export type SkillLimitReason = "bytes" | "files";

/** A skill that the run-time limit left out of a session. */
export interface SkillOmission {
  plugin_id: string;
  name: string;
  bytes: number;
  files: number;
  reason: SkillLimitReason;
}

export interface SkillLimitNotice {
  skills: SkillOmission[];
  max_bytes: number;
  max_files: number;
}

export interface SkillUsage {
  bytes: number;
  files: number;
}

/** The `skill_limit` field of a 413 SKILL_LIMIT_EXCEEDED response: the acting
 * user's usage after the change and the limits. */
export interface SkillLimitDetails {
  usage: SkillUsage;
  max_bytes: number;
  max_files: number;
}

export interface SkillLimitUser {
  user_id: string;
  email: string;
  usage: SkillUsage;
  skills_not_loaded: number;
}

export interface SkillLimitUsersResponse {
  max_bytes: number;
  max_files: number;
  users: SkillLimitUser[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isSkillLimitBody(
  body: unknown
): body is { skill_limit: SkillLimitDetails } {
  return (
    isRecord(body) &&
    body.error_code === SKILL_LIMIT_EXCEEDED &&
    isRecord(body.skill_limit)
  );
}

/** The refused write's limit details, from a failed request's body. */
export function skillLimitOf(error: unknown): SkillLimitDetails | null {
  const body: unknown = error instanceof FetchError ? error.info : null;
  return isSkillLimitBody(body) ? body.skill_limit : null;
}
