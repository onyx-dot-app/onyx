"use client";

import { useState, useEffect } from "react";
import { Text } from "@opal/components";
import { Button } from "@opal/components/buttons/button/components";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Separator from "@/refresh-components/Separator";
import { toast } from "@/hooks/useToast";
import FieldMappingTable from "@/app/admin/proposal-review/components/FieldMappingTable";
import type {
  ConfigResponse,
  ConfigUpdate,
} from "@/app/admin/proposal-review/interfaces";

interface SettingsFormProps {
  config: ConfigResponse;
  onSave: (update: ConfigUpdate) => Promise<void>;
}

function SettingsForm({ config, onSave }: SettingsFormProps) {
  const [jiraProjectKey, setJiraProjectKey] = useState(
    config.jira_project_key || ""
  );
  const [fieldMapping, setFieldMapping] = useState<Record<string, string>>(
    (config.field_mapping as Record<string, string>) || {}
  );
  const [jiraWriteback, setJiraWriteback] = useState<Record<string, string>>(
    (config.jira_writeback as Record<string, string>) || {}
  );
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setJiraProjectKey(config.jira_project_key || "");
    setFieldMapping((config.field_mapping as Record<string, string>) || {});
    setJiraWriteback((config.jira_writeback as Record<string, string>) || {});
  }, [config]);

  async function handleSave() {
    setSaving(true);
    try {
      await onSave({
        jira_project_key: jiraProjectKey || null,
        field_mapping:
          Object.keys(fieldMapping).length > 0 ? fieldMapping : null,
        jira_writeback:
          Object.keys(jiraWriteback).length > 0 ? jiraWriteback : null,
      });
      toast.success("Settings saved.");
    } catch {
      toast.error("Failed to save settings.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-4">
        <Text font="heading-h2" color="text-01">
          Jira Integration
        </Text>
        <Text font="main-ui-body" color="text-03" as="p">
          Configure how proposals are sourced from Jira and how results are
          written back.
        </Text>

        <div className="flex flex-col gap-1">
          <Text font="main-ui-action" color="text-02">
            Jira Project Key
          </Text>
          <InputTypeIn
            value={jiraProjectKey}
            onChange={(e) => setJiraProjectKey(e.target.value)}
            placeholder="e.g., OCGA"
            showClearButton={false}
          />
        </div>

        <FieldMappingTable
          title="Field Mapping"
          description="Map Jira field keys to display names used in the review interface."
          mapping={fieldMapping}
          onUpdate={setFieldMapping}
          keyLabel="Jira Field"
          valueLabel="Display Name"
        />

        <FieldMappingTable
          title="Write-back Configuration"
          description="Map review outcomes to Jira field values for automatic status sync."
          mapping={jiraWriteback}
          onUpdate={setJiraWriteback}
          keyLabel="Outcome"
          valueLabel="Jira Value"
        />
      </div>

      <Separator noPadding />

      <div className="flex items-center gap-4">
        <Button onClick={handleSave} disabled={saving}>
          {saving ? "Saving..." : "Save Settings"}
        </Button>
      </div>
    </div>
  );
}

export default SettingsForm;
