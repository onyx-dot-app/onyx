"use client";

import { Card, Checkbox, Text } from "@opal/components";
import { SvgMcp } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { cn } from "@opal/utils";
import useUserExternalApps from "@/hooks/useUserExternalApps";
import { useCraftMcpServers } from "@/lib/tools/hooks";
import { getActionIcon } from "@/lib/tools/mcpUtils";
import { getAppTypeLogo } from "@/app/craft/v1/apps/registry";

interface PreApprovalPickerProps {
  selectedAppIds: number[];
  selectedMcpServerIds: number[];
  onAppChange: (ids: number[]) => void;
  onMcpServerChange: (ids: number[]) => void;
}

function toggledIds(selectedIds: number[], id: number): number[] {
  return selectedIds.includes(id)
    ? selectedIds.filter((selectedId) => selectedId !== id)
    : [...selectedIds, id];
}

export default function PreApprovalPicker({
  selectedAppIds,
  selectedMcpServerIds,
  onAppChange,
  onMcpServerChange,
}: PreApprovalPickerProps) {
  const {
    data: apps,
    isLoading: appsLoading,
    error: appsError,
  } = useUserExternalApps();
  const {
    data: mcpData,
    isLoading: mcpLoading,
    error: mcpError,
  } = useCraftMcpServers();

  const appOptions: PreApprovalOption[] = (apps ?? []).map((app) => ({
    id: app.id,
    name: app.name,
    status: app.authenticated ? "Connected" : "Connection required",
    icon: getAppTypeLogo(app.app_type),
    testId: `pre-approval-app-${app.id}`,
  }));
  const visibleMcpServers = mcpData?.mcp_servers ?? [];
  const visibleMcpServerIds = new Set(
    visibleMcpServers.map((server) => server.id)
  );
  const mcpOptions: PreApprovalOption[] = [
    ...visibleMcpServers.map((server) => ({
      id: server.id,
      name: server.name,
      status: server.craft_connected ? "Connected" : "Connection required",
      icon: getActionIcon(server.server_url, server.name),
      testId: `pre-approval-mcp-server-${server.id}`,
    })),
    ...(mcpData || mcpError
      ? selectedMcpServerIds
          .filter((id) => !visibleMcpServerIds.has(id))
          .map((id) => ({
            id,
            name: `MCP server #${id}`,
            status: "No longer available",
            icon: SvgMcp,
            testId: `pre-approval-mcp-server-${id}`,
          }))
      : []),
  ];
  const hasOptions = appOptions.length > 0 || mcpOptions.length > 0;

  if ((appsLoading || mcpLoading) && !hasOptions) {
    return (
      <Card background="none" border="dashed" rounding={4}>
        <Text font="secondary-body" color="text-03">
          Loading apps and MCP servers…
        </Text>
      </Card>
    );
  }

  if ((appsError || mcpError) && !hasOptions) {
    return (
      <Card background="none" border="dashed" rounding={4}>
        <Text font="secondary-body" color="text-03">
          Couldn’t load apps and MCP servers. Refresh to try again.
        </Text>
      </Card>
    );
  }

  if (!hasOptions) {
    return (
      <Card background="none" border="dashed" rounding={4}>
        <Text font="secondary-body" color="text-03">
          No apps or MCP servers are available in Craft yet.
        </Text>
      </Card>
    );
  }

  return (
    <div
      className="flex w-full flex-col gap-4"
      data-testid="pre-approval-picker"
    >
      {(appsError || mcpError) && (
        <Card background="none" border="dashed" rounding={4}>
          <Text font="secondary-body" color="text-03">
            Some pre-approval options couldn’t load. Refresh to try again.
          </Text>
        </Card>
      )}
      {appOptions.length > 0 && (
        <PreApprovalGroup
          title="Apps"
          options={appOptions}
          selectedIds={selectedAppIds}
          onToggle={(id) => onAppChange(toggledIds(selectedAppIds, id))}
        />
      )}
      {mcpOptions.length > 0 && (
        <PreApprovalGroup
          title="MCP servers"
          options={mcpOptions}
          selectedIds={selectedMcpServerIds}
          onToggle={(id) =>
            onMcpServerChange(toggledIds(selectedMcpServerIds, id))
          }
        />
      )}
    </div>
  );
}

interface PreApprovalOption {
  id: number;
  name: string;
  status: string;
  icon: IconFunctionComponent;
  testId: string;
}

interface PreApprovalGroupProps {
  title: string;
  options: PreApprovalOption[];
  selectedIds: number[];
  onToggle: (id: number) => void;
}

function PreApprovalGroup({
  title,
  options,
  selectedIds,
  onToggle,
}: PreApprovalGroupProps) {
  const selected = new Set(selectedIds);
  return (
    <section className="flex flex-col gap-2" aria-label={title}>
      <Text as="h3" font="main-ui-action" color="text-03">
        {title}
      </Text>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {options.map((option) => (
          <PreApprovalRow
            key={option.id}
            option={option}
            checked={selected.has(option.id)}
            onToggle={() => onToggle(option.id)}
          />
        ))}
      </div>
    </section>
  );
}

interface PreApprovalRowProps {
  option: PreApprovalOption;
  checked: boolean;
  onToggle: () => void;
}

function PreApprovalRow({ option, checked, onToggle }: PreApprovalRowProps) {
  const Logo = option.icon;
  const checkboxId = `${option.testId}-checkbox`;
  const statusId = `${option.testId}-status`;
  return (
    <div
      className={cn(
        "rounded-12 focus-within:outline-none focus-within:ring-2 focus-within:ring-action-selection-04",
        checked && "ring-2 ring-action-selection-04"
      )}
      data-testid={option.testId}
    >
      <Card background="light" border="solid" rounding={4}>
        <label
          className="flex w-full cursor-pointer items-center gap-3"
          htmlFor={checkboxId}
        >
          <Logo className="w-8 h-8" />
          <div className="flex-1 flex flex-col gap-1 min-w-0">
            <Text font="main-ui-action">{option.name}</Text>
            <Text id={statusId} font="secondary-body" color="text-03">
              {option.status}
            </Text>
          </div>
          <Checkbox
            id={checkboxId}
            aria-label={option.name}
            aria-describedby={statusId}
            checked={checked}
            onCheckedChange={onToggle}
          />
        </label>
      </Card>
    </div>
  );
}
