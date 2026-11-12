/**
 * Per-user skill limits: the 413 a refused write returns, the skills a limit
 * left out, and the users past the write limit.
 *
 * Pairs with `backend/onyx/skills/limits.py` and `backend/onyx/db/skill_limit.py`.
 */

import { useCallback } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { FetchError } from "@/lib/fetcher";

export const SKILL_LIMIT_EXCEEDED = "SKILL_LIMIT_EXCEEDED";

export type SkillLimitReason = "bytes" | "files";

/** A skill that a limit left out of a session, or turned off at app connect. */
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

function isUsage(value: unknown): value is SkillUsage {
  return (
    isRecord(value) &&
    typeof value.bytes === "number" &&
    typeof value.files === "number"
  );
}

function isSkillLimitDetails(value: unknown): value is SkillLimitDetails {
  return (
    isRecord(value) &&
    typeof value.users_over === "number" &&
    typeof value.max_bytes === "number" &&
    typeof value.max_files === "number" &&
    (value.usage === null || isUsage(value.usage))
  );
}

function isSkillLimitBody(
  body: unknown
): body is { error_code: string; skill_limit: SkillLimitDetails } {
  return (
    isRecord(body) &&
    body.error_code === SKILL_LIMIT_EXCEEDED &&
    isSkillLimitDetails(body.skill_limit)
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

function isOmission(value: unknown): value is SkillOmission {
  return (
    isRecord(value) &&
    typeof value.plugin_id === "string" &&
    typeof value.name === "string" &&
    typeof value.bytes === "number" &&
    typeof value.files === "number" &&
    (value.reason === "bytes" || value.reason === "files")
  );
}

/** Checks a `SkillLimitNotice` from an untyped channel, such as an OAuth completion message. */
export function isSkillLimitNotice(value: unknown): value is SkillLimitNotice {
  return (
    isRecord(value) &&
    Array.isArray(value.skills) &&
    value.skills.every(isOmission) &&
    typeof value.max_bytes === "number" &&
    typeof value.max_files === "number"
  );
}

const BYTE_UNITS = ["byte", "kilobyte", "megabyte", "gigabyte"] as const;

/** A binary size in the viewer's locale, such as "500 MB" for 500 MiB. */
export function formatSkillSize(
  format: ReturnType<typeof useFormatter>,
  bytes: number,
  fractionDigits = 1
): string {
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
    maximumFractionDigits: fractionDigits,
  });
}

export interface SkillLimitCopy {
  formatSize: (bytes: number) => string;
  /** One skill and its size, plus its file count when files are the reason. */
  omissionLabel: (omission: SkillOmission) => string;
  /** Why a write was refused: the user's usage, or the number of users. */
  refusal: (limit: SkillLimitDetails) => string;
  /** The refusal for a 413 SKILL_LIMIT_EXCEEDED error, else null. */
  errorMessage: (error: unknown) => string | null;
  /** The refusal, else the error's message, else `fallback`. */
  describeError: (error: unknown, fallback: string) => string;
}

export function useSkillLimitCopy(): SkillLimitCopy {
  const t = useTranslations("skills.limit");
  const format = useFormatter();
  const formatSize = useCallback(
    (bytes: number) => formatSkillSize(format, bytes),
    [format]
  );
  const omissionLabel = useCallback(
    (omission: SkillOmission) =>
      omission.reason === "files"
        ? t("omission.withFiles", {
            name: omission.name,
            size: formatSize(omission.bytes),
            files: omission.files,
          })
        : t("omission.size", {
            name: omission.name,
            size: formatSize(omission.bytes),
          }),
    [t, formatSize]
  );
  const refusal = useCallback(
    (limit: SkillLimitDetails) => {
      const values = {
        maxSize: formatSize(limit.max_bytes),
        maxFiles: limit.max_files,
      };
      if (limit.usage === null)
        return t("refused.users", { ...values, count: limit.users_over });
      // Usage just past the limit must not read as equal to it.
      const size =
        formatSize(limit.usage.bytes) === values.maxSize
          ? formatSkillSize(format, limit.usage.bytes, 2)
          : formatSize(limit.usage.bytes);
      const usage = { ...values, size, files: limit.usage.files };
      return limit.users_over > 1
        ? t("refused.youAndUsers", { ...usage, others: limit.users_over - 1 })
        : t("refused.you", usage);
    },
    [t, format, formatSize]
  );
  const errorMessage = useCallback(
    (error: unknown) => {
      const limit = skillLimitOf(error);
      return limit === null ? null : refusal(limit);
    },
    [refusal]
  );
  const describeError = useCallback(
    (error: unknown, fallback: string) =>
      errorMessage(error) ??
      (error instanceof Error && error.message ? error.message : fallback),
    [errorMessage]
  );
  return { formatSize, omissionLabel, refusal, errorMessage, describeError };
}
