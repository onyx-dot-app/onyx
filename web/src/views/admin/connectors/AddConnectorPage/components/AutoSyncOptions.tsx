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
  const tNotice = useTranslations(
    "admin.connectorsList.settings.documentAccess.sync.sourceNotice"
  );
  const { noticeKey, fields } = autoSyncConfigBySource[connectorType];

  if (!noticeKey && !fields) {
    return null;
  }

  return (
    <Section gap={3} alignItems="stretch" height="fit">
      {noticeKey && (
        <Text font="secondary-body" color="text-03" as="p">
          {tNotice(noticeKey)}
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
