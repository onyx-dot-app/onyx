"use client";

import { useTranslations } from "next-intl";
import useSWR from "swr";
import { MessageCard, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useFormatBytes } from "@/hooks/useFormatBytes";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { SkillLimitUsersResponse } from "@/lib/skills/limits";

// Users the banner names; the rest show as a count.
const SHOWN_USERS = 10;

/** Admin banner: the active users past the per-user skill limit. */
export default function SkillLimitUsersBanner() {
  const t = useTranslations("skills.limit.banner");
  const formatBytes = useFormatBytes();
  const { data } = useSWR<SkillLimitUsersResponse, Error>(
    SWR_KEYS.skillLimitUsers,
    errorHandlingFetcher
  );
  if (!data || data.users.length === 0) return null;

  return (
    <MessageCard
      variant="warning"
      title={t("title", { count: data.users.length })}
      titleMaxLines={undefined}
      description={t("description", {
        maxSize: formatBytes(data.max_bytes),
        maxFiles: data.max_files,
      })}
      bottomChildren={
        <Section height="auto" alignItems="stretch" gap={0.5} padding={0.5}>
          {data.users.slice(0, SHOWN_USERS).map((user) => (
            <Text
              key={user.user_id}
              font="secondary-body"
              color="text-03"
              as="p"
            >
              {t("user", {
                email: user.email,
                size: formatBytes(user.usage.bytes),
                files: user.usage.files,
                notLoaded: user.skills_not_loaded,
              })}
            </Text>
          ))}
          {data.users.length > SHOWN_USERS && (
            <Text font="secondary-body" color="text-03" as="p">
              {t("more", { count: data.users.length - SHOWN_USERS })}
            </Text>
          )}
        </Section>
      }
    />
  );
}
