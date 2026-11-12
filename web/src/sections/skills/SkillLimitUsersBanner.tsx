"use client";

import { useFormatter, useTranslations } from "next-intl";
import useSWR from "swr";
import { MessageCard, Table, Text, type TableColumn } from "@opal/components";
import { Section } from "@opal/layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  useSkillLimitCopy,
  type SkillLimitUser,
  type SkillLimitUsersResponse,
} from "@/lib/skills/limits";

/** Admin banner: the active users past the 500 MB or 5,000 file skill limit. */
export default function SkillLimitUsersBanner() {
  const t = useTranslations("skills.limit.banner");
  const format = useFormatter();
  const { formatSize } = useSkillLimitCopy();
  const { data } = useSWR<SkillLimitUsersResponse, Error>(
    SWR_KEYS.skillLimitUsers,
    errorHandlingFetcher
  );
  if (!data || data.users.length === 0) return null;

  const columns: TableColumn<SkillLimitUser>[] = [
    {
      kind: "data",
      field: "email",
      title: t("columns.user"),
      weight: 40,
      truncate: true,
      cell: (email) => (
        <Text font="main-ui-body" color="text-04" maxLines={1}>
          {email}
        </Text>
      ),
    },
    {
      kind: "data",
      field: "bytes",
      title: t("columns.size"),
      weight: 20,
      cell: (bytes) => (
        <Text font="main-ui-body" color="text-03">
          {formatSize(bytes)}
        </Text>
      ),
    },
    {
      kind: "data",
      field: "files",
      title: t("columns.files"),
      weight: 20,
      cell: (files) => (
        <Text font="main-ui-body" color="text-03">
          {format.number(files)}
        </Text>
      ),
    },
    {
      kind: "data",
      field: "skills_not_loaded",
      title: t("columns.notLoaded"),
      weight: 20,
      cell: (count) => (
        <Text font="main-ui-body" color="text-03">
          {format.number(count)}
        </Text>
      ),
    },
  ];

  return (
    <MessageCard
      variant="warning"
      title={t("title", { count: data.users.length })}
      titleMaxLines={undefined}
      description={t("description", {
        maxSize: formatSize(data.max_bytes),
        maxFiles: data.max_files,
        runtimeSize: formatSize(data.runtime_max_bytes),
      })}
      bottomChildren={
        <Section height="auto" alignItems="stretch" padding={0.5}>
          <Table
            label={t("tableLabel")}
            items={data.users}
            columns={columns}
            getRowId={(row) => row.user_id}
            pageSize={10}
            size={2.25}
            initialSorting={[{ id: "bytes", desc: true }]}
          />
        </Section>
      }
    />
  );
}
