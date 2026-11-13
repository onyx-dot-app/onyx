"use client";

import { useFormatter, useTranslations } from "next-intl";
import { KeyValue, Section } from "@opal/layouts";
import { escapeMarkdown, markdown } from "@opal/utils";
import { useSettings } from "@/lib/settings/hooks";
import { useInstanceUrl } from "@/lib/app/hooks";
import { CHANGELOG_URL, commitUrl } from "@/lib/app/utils";

/**
 * The About page's rows: the app's version, the git details of the server's
 * build, and this instance's URL.
 */
export function AboutDetails() {
  const t = useTranslations("accountPopover.about");
  const format = useFormatter();
  const { version, commit, commit_date, git_ref } = useSettings();
  const instanceUrl = useInstanceUrl();
  const unavailable = t("unavailable");
  return (
    <Section gap={0.5} padding={0.5} alignItems="stretch">
      <KeyValue
        label={t("version.label")}
        value={markdown(
          `[${escapeMarkdown(version ?? "dev")}](${CHANGELOG_URL})`
        )}
      />
      <KeyValue
        label={t("ref.label")}
        value={git_ref ?? unavailable}
        mono={!!git_ref}
      />
      <KeyValue
        label={t("commit.label")}
        value={
          commit
            ? markdown(`[${commit.slice(0, 7)}](${commitUrl(commit)})`)
            : unavailable
        }
        mono={!!commit}
      />
      <KeyValue
        label={t("commitDate.label")}
        value={
          commit_date
            ? format.dateTime(new Date(commit_date), {
                dateStyle: "medium",
                timeStyle: "short",
              })
            : unavailable
        }
      />
      <KeyValue
        label={t("instanceUrl.label")}
        value={instanceUrl ?? unavailable}
      />
    </Section>
  );
}
