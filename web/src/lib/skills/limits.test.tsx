/**
 * @jest-environment jsdom
 */
import type { ReactNode } from "react";
import { NextIntlClientProvider } from "next-intl";
import { renderHook } from "@tests/setup/test-utils";
import englishMessages from "@/i18n/messages/en.json";
import { FetchError } from "@/lib/fetcher";
import { setSkillEnabled } from "@/lib/skills/api";
import {
  isSkillLimitNotice,
  skillLimitOf,
  useSkillLimitCopy,
  type SkillLimitDetails,
} from "@/lib/skills/limits";

const MB = 1024 * 1024;
const LIMITS = { max_bytes: 500 * MB, max_files: 5000 };

function body(limit: SkillLimitDetails) {
  return {
    error_code: "SKILL_LIMIT_EXCEEDED",
    detail: "This would put your skills past the limit.",
    skill_limit: limit,
  };
}

function IntlWrapper({ children }: { children: ReactNode }) {
  return (
    <NextIntlClientProvider locale="en" messages={englishMessages}>
      {children}
    </NextIntlClientProvider>
  );
}

function copy() {
  return renderHook(() => useSkillLimitCopy(), { wrapper: IntlWrapper }).result
    .current;
}

describe("skill limit refusals", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("shows a user their usage", () => {
    const limit: SkillLimitDetails = {
      ...LIMITS,
      users_over: 1,
      usage: { bytes: 512 * MB, files: 120 },
    };
    expect(copy().refusal(limit)).toBe(
      "This change puts you past the skill limit. You would use 512 MB of 500 MB and 120 of 5,000 files. Turn off skills you do not use, then try again."
    );
  });

  it("shows usage just past the limit with more digits", () => {
    const limit: SkillLimitDetails = {
      ...LIMITS,
      users_over: 1,
      usage: { bytes: 500 * MB + 20 * 1024, files: 75 },
    };
    expect(copy().refusal(limit)).toMatch(/You would use 500.02 MB of 500 MB/);
  });

  it("shows an admin the number of users who would go over", () => {
    const limit: SkillLimitDetails = { ...LIMITS, users_over: 3, usage: null };
    expect(copy().refusal(limit)).toBe(
      "This change puts 3 users past the skill limit of 500 MB or 5,000 files. Choose a narrower setting, or ask them to turn off skills."
    );
  });

  it("names the other users when the acting user is one of them", () => {
    const limit: SkillLimitDetails = {
      ...LIMITS,
      users_over: 2,
      usage: { bytes: 501 * MB, files: 10 },
    };
    expect(copy().refusal(limit)).toMatch(
      /^This change puts you and 1 other user past the skill limit\. You would use 501 MB of 500 MB/
    );
  });

  it("reads the refusal from a skills API error", async () => {
    const limit: SkillLimitDetails = {
      ...LIMITS,
      users_over: 1,
      usage: { bytes: 600 * MB, files: 30 },
    };
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 413,
      json: async () => body(limit),
    } as Response);

    const error = await setSkillEnabled("skill-1", true).catch(
      (caught: unknown) => caught
    );

    expect(skillLimitOf(error)).toEqual(limit);
    expect(copy().describeError(error, "fallback")).toMatch(
      /You would use 600 MB of 500 MB and 30 of 5,000 files/
    );
  });

  it("reads the refusal from a FetchError", () => {
    const limit: SkillLimitDetails = { ...LIMITS, users_over: 4, usage: null };
    const error = new FetchError("Request failed", 413, body(limit));
    expect(copy().errorMessage(error)).toMatch(/^This change puts 4 users/);
  });

  it("keeps other errors as they are", () => {
    const { errorMessage, describeError } = copy();
    expect(errorMessage(new Error("Name taken"))).toBeNull();
    expect(describeError(new Error("Name taken"), "fallback")).toBe(
      "Name taken"
    );
    expect(describeError("oops", "fallback")).toBe("fallback");
  });

  it("checks a left-off notice and rejects other shapes", () => {
    const notice = {
      ...LIMITS,
      skills: [
        {
          plugin_id: "p1",
          name: "slack-digest",
          bytes: 2 * MB,
          files: 3,
          reason: "bytes",
        },
      ],
    };
    expect(isSkillLimitNotice(notice)).toBe(true);
    expect(isSkillLimitNotice({ ...notice, skills: [{}] })).toBe(false);
    expect(isSkillLimitNotice(undefined)).toBe(false);
  });
});
