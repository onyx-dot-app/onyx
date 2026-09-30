import { TextFormField } from "@/components/Field";
import { ValidAutoSyncSource } from "@/lib/types";
import { Divider, Text } from "@opal/components";
import { autoSyncConfigBySource } from "@/lib/connectors/AutoSyncOptionFields";

export function AutoSyncOptions({
  connectorType,
}: {
  connectorType: ValidAutoSyncSource;
}) {
  const { notice, fields } = autoSyncConfigBySource[connectorType];

  if (!notice && !fields) {
    return null;
  }

  return (
    <div>
      <Divider />
      {notice && (
        <div className="mb-4">
          <Text font="secondary-body" color="text-03">
            {notice}
          </Text>
        </div>
      )}
      {Object.entries(fields ?? {}).map(([key, config]) => (
        <div key={key} className="mb-4">
          <TextFormField
            name={`auto_sync_options.${key}`}
            label={config.label}
            subtext={config.subtext}
          />
        </div>
      ))}
    </div>
  );
}
