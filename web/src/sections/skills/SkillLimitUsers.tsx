"use client";

import { useMemo } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  Button,
  MessageCard,
  Table,
  Text,
  type TableColumn,
} from "@opal/components";
import { Section } from "@opal/layouts";
import useScreenSize from "@opal/hooks/useScreenSize";
import { useSkillLimitUsers } from "@/lib/skills/hooks";
import { formatSkillSize, type SkillLimitUserUsage } from "@/lib/skills/limits";

interface UsageCellProps {
  row: SkillLimitUserUsage;
}

function SizeCell({ row: { usage } }: UsageCellProps) {
  const t = useTranslations("skills.limit.admin");
  const format = useFormatter();
  const size = formatSkillSize(format, usage.charged_bytes);
  return (
    <Text font="main-ui-body" color="text-04" wordWrap="wrap-anywhere">
      {usage.unknown_skill_count > 0
        ? t("size.estimated", { size, unknown: usage.unknown_skill_count })
        : size}
    </Text>
  );
}

function FilesCell({ row: { usage } }: UsageCellProps) {
  const t = useTranslations("skills.limit.admin");
  return (
    <Text font="main-ui-body" color="text-04" wordWrap="wrap-anywhere">
      {t(usage.unknown_skill_count > 0 ? "files.estimated" : "files.measured", {
        files: usage.charged_files,
      })}
    </Text>
  );
}

function OmittedCell({ row }: UsageCellProps) {
  const t = useTranslations("skills.limit.admin");
  const count = row.last_delivery_omitted_skill_count;
  return (
    <Text font="main-ui-body" color="text-04" wordWrap="wrap-anywhere">
      {count === null ? t("omitted.none") : t("omitted.count", { count })}
    </Text>
  );
}

function UserCell({ row, stacked }: UsageCellProps & { stacked: boolean }) {
  const t = useTranslations("skills.limit.admin");
  return (
    <Section height="auto" alignItems="start" gap={0.5} className="my-2">
      <Text font="main-ui-action" color="text-05" wordWrap="wrap-anywhere">
        {row.user.email}
      </Text>
      {stacked && (
        <>
          <Section
            flexDirection="row"
            justifyContent="start"
            height="auto"
            gap={1}
            wrap
          >
            <Text font="secondary-body" color="text-03">
              {t("columns.size")}
            </Text>
            <SizeCell row={row} />
          </Section>
          <Section
            flexDirection="row"
            justifyContent="start"
            height="auto"
            gap={1}
            wrap
          >
            <Text font="secondary-body" color="text-03">
              {t("columns.files")}
            </Text>
            <FilesCell row={row} />
          </Section>
          <Section
            flexDirection="row"
            justifyContent="start"
            height="auto"
            gap={1}
            wrap
          >
            <Text font="secondary-body" color="text-03">
              {t("columns.omitted")}
            </Text>
            <OmittedCell row={row} />
          </Section>
        </>
      )}
    </Section>
  );
}

/**
 * Admin banner and table of users past the Skill write limit. Mounted only
 * for global Skill managers; nothing is requested for anyone else.
 */
export default function SkillLimitUsers() {
  const t = useTranslations("skills.limit.admin");
  const format = useFormatter();
  const { isMobile } = useScreenSize();
  const { allowed, users, error, isLoading, refresh } = useSkillLimitUsers();

  const columns = useMemo<TableColumn<SkillLimitUserUsage>[]>(() => {
    const user: TableColumn<SkillLimitUserUsage> = {
      kind: "display",
      id: "user",
      title: t("columns.user"),
      width: { weight: 40, minWidth: 120 },
      hideable: false,
      cell: (row) => <UserCell row={row} stacked={isMobile} />,
    };
    if (isMobile) return [user];
    return [
      user,
      {
        kind: "display",
        id: "size",
        title: t("columns.size"),
        width: { weight: 20, minWidth: 112 },
        hideable: false,
        cell: (row) => <SizeCell row={row} />,
      },
      {
        kind: "display",
        id: "files",
        title: t("columns.files"),
        width: { weight: 16, minWidth: 96 },
        hideable: false,
        cell: (row) => <FilesCell row={row} />,
      },
      {
        kind: "display",
        id: "omitted",
        title: t("columns.omitted"),
        width: { weight: 24, minWidth: 128 },
        hideable: false,
        cell: (row) => <OmittedCell row={row} />,
      },
    ];
  }, [t, isMobile]);

  if (!allowed) return null;

  if (error) {
    return (
      <MessageCard
        variant="error"
        title={t("loadError")}
        rightChildren={
          <Button prominence="secondary" onClick={() => void refresh()}>
            {t("retry")}
          </Button>
        }
      />
    );
  }

  if (isLoading && !users) {
    return (
      <Text as="p" role="status" font="secondary-body" color="text-03">
        {t("loading")}
      </Text>
    );
  }

  const first = users?.[0];
  if (!users || !first) return null;

  return (
    <Section height="auto" alignItems="stretch" gap={2}>
      <MessageCard
        variant="warning"
        title={t("title", { count: users.length })}
        description={t("description", {
          maxSize: formatSkillSize(format, first.usage.max_bytes),
          maxFiles: first.usage.max_files,
        })}
      />
      <Table
        label={t("tableLabel")}
        rowHeight="content"
        items={users}
        columns={columns}
        getRowId={(row) => row.user.id}
        pageSize={10}
        footer={users.length > 10}
      />
    </Section>
  );
}
