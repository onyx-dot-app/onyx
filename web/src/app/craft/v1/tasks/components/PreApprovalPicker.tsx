"use client";

import { useCallback } from "react";
import { Card, Checkbox, Text } from "@opal/components";
import { cn } from "@opal/utils";
import useUserExternalApps from "@/hooks/useUserExternalApps";
import {
  getAppTypeLogo,
  type ExternalAppUserResponse,
} from "@/app/craft/v1/apps/registry";

interface PreApprovalPickerProps {
  selectedIds: number[];
  onChange: (ids: number[]) => void;
}

export default function PreApprovalPicker({
  selectedIds,
  onChange,
}: PreApprovalPickerProps) {
  const { data, isLoading, error } = useUserExternalApps();

  const selected = new Set(selectedIds);
  const toggle = useCallback(
    (id: number) => {
      const next = new Set(selectedIds);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      onChange(Array.from(next));
    },
    [selectedIds, onChange]
  );

  if (isLoading) {
    return (
      <Card background="none" border="dashed" rounding="lg">
        <Text font="secondary-body" color="text-03">
          Loading apps…
        </Text>
      </Card>
    );
  }

  if (error) {
    return (
      <Card background="none" border="dashed" rounding="lg">
        <Text font="secondary-body" color="text-03">
          Couldn’t load your apps. Refresh to try again.
        </Text>
      </Card>
    );
  }

  if (!data || data.length === 0) {
    return (
      <Card background="none" border="dashed" rounding="lg">
        <Text font="secondary-body" color="text-03">
          No external apps are enabled for your org yet. Ask an admin to enable
          one.
        </Text>
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
      {data.map((app) => (
        <PreApprovalRow
          key={app.id}
          app={app}
          checked={selected.has(app.id)}
          onToggle={() => toggle(app.id)}
        />
      ))}
    </div>
  );
}

interface PreApprovalRowProps {
  app: ExternalAppUserResponse;
  checked: boolean;
  onToggle: () => void;
}

function PreApprovalRow({ app, checked, onToggle }: PreApprovalRowProps) {
  const Logo = getAppTypeLogo(app.app_type);
  return (
    <div
      role="checkbox"
      aria-checked={checked}
      aria-label={app.name}
      tabIndex={0}
      onClick={onToggle}
      onKeyDown={(e) => {
        if (e.key === " " || e.key === "Enter") {
          e.preventDefault();
          onToggle();
        }
      }}
      className={cn(
        "rounded-12 cursor-pointer transition-shadow",
        checked && "ring-2 ring-action-link-04"
      )}
      data-testid={`pre-approval-app-${app.id}`}
    >
      <Card background="light" border="solid" rounding="lg">
        <div className="flex items-center gap-3 w-full">
          <Logo className="w-8 h-8" />
          <div className="flex-1 flex flex-col gap-0.5 min-w-0">
            <Text font="main-ui-action">{app.name}</Text>
            <Text font="secondary-body" color="text-03">
              {app.description}
            </Text>
          </div>
          {/* Visual only — the row owns clicks/keys so the control never
              double-toggles. */}
          <div className="pointer-events-none">
            <Checkbox checked={checked} />
          </div>
        </div>
      </Card>
    </div>
  );
}
