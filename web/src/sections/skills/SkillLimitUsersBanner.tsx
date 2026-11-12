"use client";

import { useTranslations } from "next-intl";
import useSWR from "swr";
import { MessageCard, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  useSkillLimitCopy,
  type SkillLimitUsersResponse,
} from "@/lib/skills/limits";

/** Admin banner: the active users past the per-user skill limit. */
export default function SkillLimitUsersBanner() {
  const t = useTranslations("skills.limit.banner");
  const { formatSize } = useSkillLimitCopy();
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
        maxSize: formatSize(data.max_bytes),
        maxFiles: data.max_files,
      })}
      bottomChildren={
        <Section height="auto" alignItems="stretch" gap={0.5} padding={0.5}>
          {data.users.map((user) => (
            <Text
              key={user.user_id}
              font="secondary-body"
              color="text-03"
              as="p"
            >
              {t("user", {
                email: user.email,
                size: formatSize(user.bytes),
                files: user.files,
                notLoaded: user.skills_not_loaded,
              })}
            </Text>
          ))}
        </Section>
      }
    />
  );
}
