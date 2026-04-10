"use client";

import { useState, useEffect } from "react";
import useSWR from "swr";
import { Text } from "@opal/components";
import { Button } from "@opal/components/buttons/button/components";
import Checkbox from "@/refresh-components/inputs/Checkbox";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Separator from "@/refresh-components/Separator";
import { toast } from "@/hooks/useToast";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SvgPlus, SvgTrash } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { Content } from "@opal/layouts";
import type {
  ConfigResponse,
  ConfigUpdate,
  JiraConnectorInfo,
} from "@/app/admin/proposal-review/interfaces";

const CONNECTORS_URL = "/api/proposal-review/jira-connectors";

interface SettingsFormProps {
  config: ConfigResponse;
  onSave: (update: ConfigUpdate) => Promise<void>;
  onCancel: () => void;
}

function SettingsForm({ config, onSave, onCancel }: SettingsFormProps) {
  const [connectorId, setConnectorId] = useState<number | null>(
    config.jira_connector_id
  );
  const [visibleFields, setVisibleFields] = useState<string[]>(
    config.field_mapping ?? []
  );
  const [jiraWriteback, setJiraWriteback] = useState<Record<string, string>>(
    (config.jira_writeback as Record<string, string>) || {}
  );
  const [saving, setSaving] = useState(false);
  const [fieldSearch, setFieldSearch] = useState("");

  // Writeback add-row state
  const [newWritebackKey, setNewWritebackKey] = useState("");
  const [newWritebackField, setNewWritebackField] = useState("");

  useEffect(() => {
    setConnectorId(config.jira_connector_id);
    setVisibleFields(config.field_mapping ?? []);
    setJiraWriteback((config.jira_writeback as Record<string, string>) || {});
  }, [config]);

  // Fetch available Jira connectors
  const { data: connectors, isLoading: connectorsLoading } = useSWR<
    JiraConnectorInfo[]
  >(CONNECTORS_URL, errorHandlingFetcher);

  // Fetch metadata keys from indexed documents for the selected connector
  const { data: metadataKeys, isLoading: fieldsLoading } = useSWR<string[]>(
    connectorId
      ? `/api/proposal-review/jira-connectors/${connectorId}/metadata-keys`
      : null,
    errorHandlingFetcher
  );

  const selectedConnector = (connectors ?? []).find(
    (c) => c.id === connectorId
  );

  async function handleSave() {
    setSaving(true);
    try {
      await onSave({
        jira_connector_id: connectorId,
        jira_project_key: selectedConnector?.project_key || null,
        field_mapping: visibleFields.length > 0 ? visibleFields : null,
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

  function toggleField(key: string) {
    setVisibleFields((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  }

  function handleAddWriteback() {
    if (!newWritebackKey) return;
    setJiraWriteback({
      ...jiraWriteback,
      [newWritebackKey]: newWritebackField,
    });
    setNewWritebackKey("");
    setNewWritebackField("");
  }

  const writebackEntries = Object.entries(jiraWriteback);

  // Filter metadata keys by search
  const allKeys = metadataKeys ?? [];
  const filteredKeys = fieldSearch
    ? allKeys.filter((k) => k.toLowerCase().includes(fieldSearch.toLowerCase()))
    : allKeys;

  return (
    <Section gap={2} alignItems="stretch" height="auto">
      {/* Jira Connector Selection */}
      <Section gap={1} alignItems="stretch" height="auto">
        <Content
          sizePreset="section"
          variant="section"
          title="Jira Connector"
          description="Select which Jira connector to use for proposal sourcing."
        />

        <Section gap={0.25} alignItems="start" height="auto">
          <Text font="main-ui-action" color="text-04">
            Connector
          </Text>
          {connectorsLoading ? (
            <Text font="main-ui-body" color="text-03" as="p">
              Loading connectors...
            </Text>
          ) : connectors && connectors.length > 0 ? (
            <InputSelect
              value={connectorId != null ? String(connectorId) : undefined}
              onValueChange={(val) => {
                const newId = val ? Number(val) : null;
                if (newId !== connectorId) {
                  setConnectorId(newId);
                  setVisibleFields([]);
                }
              }}
            >
              <InputSelect.Trigger placeholder="Select a Jira connector..." />
              <InputSelect.Content>
                {connectors.map((c) => (
                  <InputSelect.Item
                    key={c.id}
                    value={String(c.id)}
                    description={
                      c.project_key ? `Project: ${c.project_key}` : undefined
                    }
                  >
                    {c.name}
                  </InputSelect.Item>
                ))}
              </InputSelect.Content>
            </InputSelect>
          ) : (
            <Text font="main-ui-body" color="text-03" as="p">
              No Jira connectors found. Add one in the Connectors settings
              first.
            </Text>
          )}
        </Section>
      </Section>

      <Separator noPadding />

      {/* Visible Fields Checklist */}
      <Section gap={1} alignItems="stretch" height="auto">
        <Content
          sizePreset="section"
          variant="section"
          title="Visible Fields"
          description="Choose which metadata fields to display in the proposal queue and review interface. If none are selected, all fields are shown."
        />

        {fieldsLoading && connectorId && (
          <Text font="secondary-body" color="text-03" as="p">
            Loading fields...
          </Text>
        )}

        {!fieldsLoading && connectorId && allKeys.length > 0 && (
          <>
            <InputTypeIn
              placeholder="Filter fields..."
              value={fieldSearch}
              onChange={(e) => setFieldSearch(e.target.value)}
              onClear={() => setFieldSearch("")}
              leftSearchIcon
            />
            <div className="flex flex-col gap-1 max-h-64 overflow-y-auto">
              {filteredKeys.map((key) => (
                <label
                  key={key}
                  className="flex items-center gap-3 px-2 py-1.5 rounded-8 cursor-pointer hover:bg-background-neutral-02"
                >
                  <Checkbox
                    checked={visibleFields.includes(key)}
                    onCheckedChange={() => toggleField(key)}
                  />
                  <Text font="main-ui-body" color="text-04">
                    {key}
                  </Text>
                </label>
              ))}
            </div>
            {visibleFields.length > 0 && (
              <Text font="secondary-body" color="text-03" as="p">
                {`${visibleFields.length} field${
                  visibleFields.length !== 1 ? "s" : ""
                } selected`}
              </Text>
            )}
          </>
        )}

        {!fieldsLoading && connectorId && allKeys.length === 0 && (
          <Text font="secondary-body" color="text-03" as="p">
            No metadata fields found. Make sure the connector has indexed some
            documents.
          </Text>
        )}

        {!connectorId && (
          <Text font="secondary-body" color="text-03" as="p">
            Select a connector above to see available fields.
          </Text>
        )}
      </Section>

      <Separator noPadding />

      {/* Write-back Configuration */}
      <Section gap={1} alignItems="stretch" height="auto">
        <Content
          sizePreset="section"
          variant="section"
          title="Write-back Configuration"
          description="Map review outcomes to Jira custom fields for automatic status sync."
        />

        {writebackEntries.length > 0 && (
          <Section gap={0.5} alignItems="stretch" height="auto">
            <div className="flex gap-3 px-1">
              <span className="flex-1">
                <Text font="secondary-action" color="text-03">
                  Outcome
                </Text>
              </span>
              <span className="flex-1">
                <Text font="secondary-action" color="text-03">
                  Jira Field
                </Text>
              </span>
              <div className="w-8" />
            </div>
            {writebackEntries.map(([key, value]) => (
              <Section
                key={key}
                flexDirection="row"
                gap={0.75}
                alignItems="center"
                height="auto"
              >
                <div className="flex-1">
                  <Text font="main-ui-body" color="text-04">
                    {key}
                  </Text>
                </div>
                <div className="flex-1">
                  <Text font="main-ui-body" color="text-04">
                    {value}
                  </Text>
                </div>
                <Button
                  icon={SvgTrash}
                  prominence="tertiary"
                  variant="danger"
                  size="sm"
                  onClick={() => {
                    const updated = { ...jiraWriteback };
                    delete updated[key];
                    setJiraWriteback(updated);
                  }}
                  tooltip="Remove"
                />
              </Section>
            ))}
          </Section>
        )}

        {connectorId && (
          <Section
            flexDirection="row"
            gap={0.75}
            alignItems="center"
            height="auto"
          >
            <div className="flex-1">
              <InputSelect
                value={newWritebackKey || undefined}
                onValueChange={setNewWritebackKey}
              >
                <InputSelect.Trigger placeholder="Select outcome..." />
                <InputSelect.Content>
                  {["decision_field_id", "completion_field_id"].map((key) => (
                    <InputSelect.Item key={key} value={key}>
                      {key === "decision_field_id"
                        ? "Decision Field"
                        : "Completion % Field"}
                    </InputSelect.Item>
                  ))}
                </InputSelect.Content>
              </InputSelect>
            </div>
            <div className="flex-1">
              {allKeys.length > 0 ? (
                <InputComboBox
                  placeholder="Search fields..."
                  value={newWritebackField}
                  onValueChange={setNewWritebackField}
                  options={allKeys.map((key) => ({
                    value: key,
                    label: key,
                  }))}
                  strict
                  leftSearchIcon
                />
              ) : (
                <Text font="secondary-body" color="text-03" as="p">
                  Select a connector first
                </Text>
              )}
            </div>
            <Button
              icon={SvgPlus}
              prominence="tertiary"
              size="sm"
              onClick={handleAddWriteback}
              disabled={!newWritebackKey || !newWritebackField}
              tooltip="Add entry"
            />
          </Section>
        )}
      </Section>

      <Separator noPadding />

      {/* Actions */}
      <Section flexDirection="row" gap={0.75} alignItems="center" height="auto">
        <Button onClick={handleSave} disabled={saving}>
          {saving ? "Saving..." : "Save"}
        </Button>
        <Button prominence="secondary" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
      </Section>
    </Section>
  );
}

export default SettingsForm;
