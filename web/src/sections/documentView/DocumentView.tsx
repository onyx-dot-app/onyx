"use client";

import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { IllustrationContent, SettingsLayouts } from "@opal/layouts";
import { SvgExternalLink } from "@opal/icons";
import { SvgNotFound } from "@opal/illustrations";
import { fetchErrorDetail } from "@/lib/fetcher";
import { useDocumentContent } from "@/lib/documentView/hooks";

const NOT_FOUND_STATUS = 404;

export interface DocumentViewProps {
  documentId: string | null;
}

export default function DocumentView({ documentId }: DocumentViewProps) {
  const t = useTranslations("documentView");
  const { data, error, isLoading } = useDocumentContent(documentId);

  if (!documentId || error?.status === NOT_FOUND_STATUS) {
    return (
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Body>
          <IllustrationContent
            illustration={SvgNotFound}
            title={t("notFound.title")}
            description={t("notFound.description")}
          />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  if (error) {
    return (
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Body>
          <IllustrationContent
            illustration={SvgNotFound}
            title={fetchErrorDetail(error) ?? t("loadFailed")}
          />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  return (
    <SettingsLayouts.Root width="lg" loading={isLoading || !data}>
      <SettingsLayouts.Header title={data?.title ?? ""}>
        {data?.link && (
          <Button
            prominence="secondary"
            size="sm"
            rightIcon={SvgExternalLink}
            href={data.link}
            target="_blank"
          >
            {t("openSource")}
          </Button>
        )}
      </SettingsLayouts.Header>
      <SettingsLayouts.Body>
        {data && (
          <div className="whitespace-pre-wrap">
            <Text as="p" font="main-ui-mono" wordWrap="wrap-anywhere">
              {data.content}
            </Text>
          </div>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
