import { TextFormField } from "@/components/Field";
import { ValidAutoSyncSource } from "@/lib/types";
import { Separator } from "@/components/ui/separator";
import { autoSyncConfigBySource } from "@/lib/connectors/AutoSyncOptionFields";

export function AutoSyncOptions({
  connectorType,
}: {
  connectorType: ValidAutoSyncSource;
}) {
  const autoSyncConfig = autoSyncConfigBySource[connectorType];

  if (Object.keys(autoSyncConfig).length === 0) {
    return null;
  }

  return (
    <div>
      <Separator />
      {Object.entries(autoSyncConfig).map(([key, config]) => (
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
