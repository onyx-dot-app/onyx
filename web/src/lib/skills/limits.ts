/**
 * Per-user skill limits: the 413 a refused write returns, the skills a
 * session left out, and the users past the write limit.
 *
 * Pairs with `backend/onyx/skills/limits.py` and `backend/onyx/db/skill_limit.py`.
 */

import { useCallback } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { FetchError, fetchErrorDetail } from "@/lib/fetcher";

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

/** The `skill_limit` field of a 413 SKILL_LIMIT_EXCEEDED response. */
export interface SkillLimitDetails {
  users_over: number;
  /** The acting user's usage after the change, when they are one of the users over. */
  usage: SkillUsage | null;
  max_bytes: number;
  max_files: number;
}

export interface SkillLimitUser {
  user_id: string;
  email: string;
  bytes: number;
  files: number;
  skills_not_loaded: number;
}

export interface SkillLimitUsersResponse {
  max_bytes: number;
  max_files: number;
  runtime_max_bytes: number;
  runtime_max_files: number;
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

/** The refused write's limit details, from a skills API error (`responseBody`) or a `FetchError`. */
export function skillLimitOf(error: unknown): SkillLimitDetails | null {
  const body =
    error instanceof FetchError
      ? error.info
      : error instanceof Error && "responseBody" in error
        ? error.responseBody
        : null;
  return isSkillLimitBody(body) ? body.skill_limit : null;
}

const BYTE_UNITS = ["byte", "kilobyte", "megabyte", "gigabyte"] as const;

export interface SkillLimitCopy {
  /** A binary size in the viewer's locale, such as "500 MB" for 500 MiB. */
  formatSize: (bytes: number) => string;
  /** The refusal of a 413 SKILL_LIMIT_EXCEEDED error, else the server's
   * detail, else `fallback`. */
  describeError: (error: unknown, fallback: string) => string;
}

export function useSkillLimitCopy(): SkillLimitCopy {
  const t = useTranslations("skills.limit.refused");
  const format = useFormatter();
  const formatSize = useCallback(
    (bytes: number) => {
      let value = bytes;
      let unit = 0;
      while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
        value /= 1024;
        unit += 1;
      }
      return format.number(value, {
        style: "unit",
        unit: BYTE_UNITS[unit],
        unitDisplay: "short",
        maximumFractionDigits: 1,
      });
    },
    [format]
  );
  const describeError = useCallback(
    (error: unknown, fallback: string) => {
      const limit = skillLimitOf(error);
      if (limit !== null) {
        const values = {
          maxSize: formatSize(limit.max_bytes),
          maxFiles: limit.max_files,
        };
        return limit.usage === null
          ? t("users", { ...values, count: limit.users_over })
          : t("you", values);
      }
      if (error instanceof FetchError)
        return fetchErrorDetail(error) ?? fallback;
      return error instanceof Error && error.message ? error.message : fallback;
    },
    [t, formatSize]
  );
  return { formatSize, describeError };
}
