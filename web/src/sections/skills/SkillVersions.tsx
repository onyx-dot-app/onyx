"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import useSWR, { useSWRConfig } from "swr";
import useSWRInfinite from "swr/infinite";
import {
  Button,
  CompactMarkdown,
  Table,
  Text,
  type TableColumn,
} from "@opal/components";
import { IllustrationContent, Section } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import useScreenSize from "@opal/hooks/useScreenSize";
import {
  listSkillVersions,
  previewSkillVersion,
  restoreSkillVersion,
} from "@/lib/skills/api";
import { canReadSkillHistory } from "@/lib/skills/permissions";
import type {
  CustomSkill,
  SkillBundleContents,
  SkillEditableDetail,
  SkillPreview,
  SkillVersion,
} from "@/lib/skills/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { isAuthStatusError, isNotFoundError } from "@/lib/fetcher";

type HistoryView =
  | { kind: "list" }
  | { kind: "preview" | "confirm"; version: SkillVersion };

type SkillVersionsProps = {
  onBusyChange: (busy: boolean) => void;
  onRestored: (skill: SkillEditableDetail) => void;
  restoreDisabled?: boolean;
} & (
  | { kind?: "active"; skill: CustomSkill }
  | { kind: "retired"; skillId: string }
);

function VersionPreview({
  skillId,
  version,
}: {
  skillId: string;
  version: SkillVersion;
}) {
  const t = useTranslations("skills.versions");
  const focusContent = useCallback(
    (node: HTMLElement | null) => node?.focus(),
    []
  );
  const { data, error, mutate } = useSWR<SkillBundleContents, Error>(
    SWR_KEYS.skillVersion(skillId, version.id),
    () => previewSkillVersion(skillId, version.id)
  );
  if (error)
    return (
      <Section height="auto">
        <IllustrationContent title={t("previewError")} />
        <Button onClick={() => void mutate()}>{t("retry")}</Button>
      </Section>
    );
  if (!data) return <IconLoader aria-label={t("loading")} />;
  return (
    <Section height="auto" alignItems="stretch" gap={3}>
      <Text
        as="h3"
        tabIndex={-1}
        ref={focusContent}
        font="heading-section"
        wordWrap="wrap-anywhere"
      >
        {data.name}
      </Text>
      <Text wordWrap="wrap-anywhere">{data.description}</Text>
      <Section
        height="auto"
        alignItems="stretch"
        padding={3}
        className="rounded-lg border border-border-02 overflow-x-auto"
      >
        <CompactMarkdown>{data.instructions_markdown}</CompactMarkdown>
      </Section>
      <Text font="main-ui-action">{t("files")}</Text>
      {data.files.length === 0 ? (
        <Text>{t("noFiles")}</Text>
      ) : (
        <ul className="m-0 ps-5 list-disc">
          {data.files.map((file) => (
            <Text as="li" key={file.path} wordWrap="wrap-anywhere">
              {file.path}
            </Text>
          ))}
        </ul>
      )}
    </Section>
  );
}

export default function SkillVersions(props: SkillVersionsProps) {
  const { onBusyChange, onRestored } = props;
  const skillId = props.kind === "retired" ? props.skillId : props.skill.id;
  const canRestore = props.kind !== "retired" && !props.skill.marketplace;
  const t = useTranslations("skills.versions");
  const format = useFormatter();
  const { isSmallScreen } = useScreenSize();
  const { mutate } = useSWRConfig();
  const allowed = props.kind === "retired" || canReadSkillHistory(props.skill);
  const {
    data: pages,
    error,
    mutate: refreshVersions,
    size,
    setSize,
    isValidating,
  } = useSWRInfinite<SkillVersion[], Error>(
    (pageIndex: number, previous: SkillVersion[] | null) => {
      if (!allowed) return null;
      if (pageIndex === 0) return [SWR_KEYS.skillVersions(skillId), null];
      const oldest = previous?.at(-1);
      return oldest && oldest.version_number > 1
        ? [SWR_KEYS.skillVersions(skillId), oldest.version_number]
        : null;
    },
    ([, beforeVersion]: [string, number | null]) =>
      listSkillVersions(skillId, beforeVersion)
  );
  const accessDenied = isAuthStatusError(error) || isNotFoundError(error);
  const versions = pages?.flat();
  const oldest = pages?.at(-1)?.at(-1);
  const hasMore = oldest !== undefined && oldest.version_number > 1;
  const olderPageCursor = useRef<number | null>(null);
  const versionLabels = useRef(new Map<number, HTMLElement>());
  const [view, setView] = useState<HistoryView>({ kind: "list" });
  const [pending, setPending] = useState(false);
  const requestPending = useRef(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const listTitle = useRef<HTMLElement | null>(null);
  const returning = useRef(false);
  const focusHeading = useCallback(
    (node: HTMLElement | null) => node?.focus(),
    []
  );
  useEffect(() => {
    if (allowed && !accessDenied) return;
    setView({ kind: "list" });
    void mutate(
      (key) =>
        typeof key === "string" &&
        key.startsWith(`${SWR_KEYS.skillVersions(skillId)}/`),
      undefined,
      { revalidate: false }
    );
  }, [allowed, accessDenied, mutate, skillId]);
  useEffect(() => {
    if (view.kind === "list" && returning.current) {
      listTitle.current?.focus();
      returning.current = false;
    }
  }, [view]);
  useEffect(() => {
    const cursor = olderPageCursor.current;
    if (isValidating) return;
    if (error) {
      olderPageCursor.current = null;
      return;
    }
    if (cursor === null) return;
    const firstOlder = pages?.flat().find((row) => row.version_number < cursor);
    const target = firstOlder
      ? versionLabels.current.get(firstOlder.version_number)
      : listTitle.current;
    target?.focus();
    olderPageCursor.current = null;
  }, [pages, isValidating, error]);

  function versionRef(version: SkillVersion) {
    return (node: HTMLElement | null) => {
      if (node) versionLabels.current.set(version.version_number, node);
      else versionLabels.current.delete(version.version_number);
    };
  }

  function back() {
    if (requestPending.current) return;
    returning.current = true;
    setView({ kind: "list" });
    setRestoreError(null);
  }

  async function restore(version: SkillVersion) {
    if (
      requestPending.current ||
      !allowed ||
      accessDenied ||
      !canRestore ||
      props.restoreDisabled ||
      !version.has_bundle
    )
      return;
    requestPending.current = true;
    setPending(true);
    onBusyChange(true);
    setRestoreError(null);
    try {
      const restored = await restoreSkillVersion(skillId, version.id);
      const preview: SkillPreview = {
        source: restored.source,
        id: restored.id,
        name: restored.name,
        description: restored.description,
        author_email: restored.author_email,
        instructions_markdown: restored.instructions_markdown,
        external_app: restored.external_app,
      };
      async function refreshHistory() {
        const refreshed = await refreshVersions();
        const last = refreshed?.at(-1)?.at(-1);
        if (oldest && last && last.version_number > oldest.version_number) {
          await setSize(size + 1);
        }
      }
      // Seed current content even when its panel has not mounted yet.
      await Promise.allSettled([
        refreshHistory(),
        mutate(SWR_KEYS.editableSkill(skillId), restored),
        mutate(SWR_KEYS.skillSharing(skillId), restored),
        mutate(SWR_KEYS.userSkillPreview(skillId), preview),
        mutate(SWR_KEYS.userSkills),
      ]);
      setNotice(t("restored"));
      returning.current = true;
      setView({ kind: "list" });
      onRestored(restored);
    } catch (error) {
      setRestoreError(
        error instanceof Error ? error.message : t("restoreError")
      );
    } finally {
      requestPending.current = false;
      setPending(false);
      onBusyChange(false);
    }
  }

  function change(version: SkillVersion) {
    return version.marketplace_revision !== null
      ? t("syncedRevision", { revision: version.marketplace_revision })
      : t(version.version_number === 1 ? "initial" : "updated");
  }

  function date(version: SkillVersion) {
    return format.dateTime(new Date(version.created_at), {
      dateStyle: "medium",
      timeStyle: "short",
    });
  }

  function versionLabel(version: SkillVersion) {
    return t("number", { version: format.number(version.version_number) });
  }

  function actions(version: SkillVersion) {
    if (!version.has_bundle)
      return (
        <Text font="secondary-body" color="text-03">
          {t("pruned")}
        </Text>
      );
    return (
      <Section
        flexDirection="row"
        wrap
        gap={2}
        height="auto"
        justifyContent="start"
      >
        <Button
          size="sm"
          prominence="secondary"
          aria-label={t("previewVersion", {
            version: format.number(version.version_number),
          })}
          onClick={() => setView({ kind: "preview", version })}
        >
          {t("preview")}
        </Button>
        {canRestore && !version.is_current && (
          <Button
            disabled={props.restoreDisabled}
            size="sm"
            prominence="secondary"
            aria-label={t("restoreVersion", {
              version: format.number(version.version_number),
            })}
            onClick={() => {
              setRestoreError(null);
              setView({ kind: "confirm", version });
            }}
          >
            {t("restore")}
          </Button>
        )}
      </Section>
    );
  }

  const columns: TableColumn<SkillVersion>[] = [
    {
      kind: "display",
      id: "version",
      title: t("version"),
      width: { weight: 14, minWidth: 72 },
      cell: (item) => (
        <Section height="auto" alignItems="start" gap={1}>
          <Text tabIndex={-1} ref={versionRef(item)}>
            {format.number(item.version_number)}
          </Text>
          {item.is_current && (
            <Text font="secondary-action">{t("current")}</Text>
          )}
        </Section>
      ),
    },
    {
      kind: "display",
      id: "change",
      title: t("change"),
      width: { weight: 25, minWidth: 100 },
      cell: (item) => <Text wordWrap="wrap-anywhere">{change(item)}</Text>,
    },
    {
      kind: "display",
      id: "creator",
      title: t("madeBy"),
      width: { weight: 24, minWidth: 100 },
      cell: (item) => (
        <Text wordWrap="wrap-anywhere">
          {item.created_by?.email ?? t("unknownCreator")}
        </Text>
      ),
    },
    {
      kind: "display",
      id: "date",
      title: t("date"),
      width: { weight: 20, minWidth: 100 },
      cell: (item) => <Text>{date(item)}</Text>,
    },
    {
      kind: "display",
      id: "actions",
      title: t("actions"),
      width: { weight: 22, minWidth: 100 },
      cell: (item) => actions(item),
    },
  ];

  if (!allowed) return null;
  if (accessDenied)
    return (
      <Section height="auto" role="alert">
        <IllustrationContent title={t("loadError")} />
        <Button onClick={() => void refreshVersions()}>{t("retry")}</Button>
      </Section>
    );
  if (view.kind !== "list")
    return (
      <Section height="auto" alignItems="stretch" gap={4} aria-busy={pending}>
        <Text as="h2" font="heading-section" tabIndex={-1} ref={focusHeading}>
          {view.kind === "confirm"
            ? t("confirmTitle", {
                version: format.number(view.version.version_number),
              })
            : versionLabel(view.version)}
        </Text>
        {view.kind === "preview" ? (
          <VersionPreview skillId={skillId} version={view.version} />
        ) : (
          <Text>{t("confirmDescription")}</Text>
        )}
        {restoreError && (
          <Text color="status-error-05" role="alert">
            {restoreError}
          </Text>
        )}
        <Section
          flexDirection="row"
          wrap
          height="auto"
          justifyContent="start"
          gap={2}
        >
          <Button prominence="secondary" disabled={pending} onClick={back}>
            {t(view.kind === "confirm" ? "cancel" : "back")}
          </Button>
          {view.kind === "confirm" && (
            <Button
              disabled={pending || props.restoreDisabled}
              onClick={() => void restore(view.version)}
            >
              {t(pending ? "restoring" : "restore")}
            </Button>
          )}
        </Section>
      </Section>
    );
  return (
    <Section height="auto" alignItems="stretch" gap={3}>
      {canRestore && props.restoreDisabled && (
        <Text role="status">{t("saveBeforeRestore")}</Text>
      )}
      <Text
        as="h2"
        font="heading-section"
        ref={(node) => {
          listTitle.current = node;
        }}
        tabIndex={-1}
      >
        {t("title")}
      </Text>
      {notice && <Text role="status">{notice}</Text>}
      {error && (
        <Section height="auto" role="alert">
          <IllustrationContent title={t("loadError")} />
          {!versions && (
            <Button onClick={() => void refreshVersions()}>{t("retry")}</Button>
          )}
        </Section>
      )}
      {!versions ? (
        !error && (
          <Section height="auto">
            <IconLoader />
            <Text>{t("loading")}</Text>
          </Section>
        )
      ) : versions.length === 0 ? (
        <IllustrationContent title={t("empty")} />
      ) : isSmallScreen ? (
        <Section
          height="auto"
          alignItems="stretch"
          gap={3}
          role="list"
          aria-label={t("title")}
        >
          {versions.map((version) => (
            <Section
              key={version.id}
              role="listitem"
              height="auto"
              alignItems="stretch"
              padding={3}
              gap={2}
              className="rounded-lg border border-border-02"
            >
              <Text
                font="main-ui-action"
                tabIndex={-1}
                ref={versionRef(version)}
              >
                {versionLabel(version)}
              </Text>
              {version.is_current && (
                <Text font="secondary-action">{t("current")}</Text>
              )}
              <Text wordWrap="wrap-anywhere">{change(version)}</Text>
              <Section height="auto" alignItems="stretch" gap={0}>
                <Text font="secondary-action">{t("madeBy")}</Text>
                <Text wordWrap="wrap-anywhere">
                  {version.created_by?.email ?? t("unknownCreator")}
                </Text>
              </Section>
              <Text>{date(version)}</Text>
              {actions(version)}
            </Section>
          ))}
        </Section>
      ) : (
        <Table
          label={t("title")}
          items={versions}
          columns={columns}
          getRowId={(version) => version.id}
          rowHeight="content"
          pageSize={false}
        />
      )}
      {(hasMore || (error && versions)) && (
        <Button
          prominence="secondary"
          aria-disabled={isValidating}
          aria-busy={isValidating}
          aria-label={t(error ? "retry" : "loadOlder")}
          onClick={() => {
            if (isValidating) return;
            if (oldest) {
              olderPageCursor.current = oldest.version_number;
            }
            if (error) void refreshVersions();
            else if (oldest) void setSize(size + 1);
          }}
        >
          {t(
            error ? "retry" : isSmallScreen ? "loadOlderCompact" : "loadOlder"
          )}
        </Button>
      )}
      {versions && isValidating && <Text role="status">{t("loading")}</Text>}
    </Section>
  );
}
