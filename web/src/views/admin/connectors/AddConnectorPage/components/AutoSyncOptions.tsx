import { Text } from "@opal/components";
import { InputVertical, Section } from "@opal/layouts";
import { useTranslations } from "next-intl";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import type { ValidAutoSyncSource } from "@/lib/connectors/types/source";
import { autoSyncConfigBySource } from "@/lib/connectors/AutoSyncOptionFields";

interface AutoSyncOptionsProps {
  connectorType: ValidAutoSyncSource;
}

/** The source's Auto Sync notice and extra fields, if it has any. */
export default function AutoSyncOptions({
  connectorType,
}: AutoSyncOptionsProps) {
  const t = useTranslations("admin.connectorsList");
  const noticeBySource: Partial<Record<ValidAutoSyncSource, string>> = {
    linear: t("linear.syncNotice"),
  };
  const notice: string | undefined = noticeBySource[connectorType];
  const { fields } = autoSyncConfigBySource[connectorType];

  if (!notice && !fields) {
    return null;
  }

  return (
    <Section gap={3} alignItems="stretch" height="fit">
      {notice && (
        <Text font="secondary-body" color="text-03" as="p">
          {notice}
        </Text>
      )}
      {Object.entries(fields ?? {}).map(([key, config]) => {
        const name = `auto_sync_options.${key}`;
        return (
          <InputVertical
            key={key}
            withLabel={name}
            title={config.label}
            description={config.subtext}
          >
            <InputTypeInField name={name} />
          </InputVertical>
        );
      })}
    </Section>
  );
}
