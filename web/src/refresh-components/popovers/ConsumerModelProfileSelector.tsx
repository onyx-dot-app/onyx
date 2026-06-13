"use client";

import { useCallback, useMemo, useState } from "react";
import {
  LineItemButton,
  Popover,
  PopoverMenu,
  SelectButton,
  Text,
} from "@opal/components";
import { SvgCheck, SvgSparkle } from "@opal/icons";
import {
  useConsumerModelCatalog,
  useConsumerModelPreference,
} from "@/hooks/useConsumerModelCatalog";
import { updateConsumerModelPreference } from "@/lib/consumerModels/svc";
import {
  findConsumerProfile,
  getConsumerProfileLabel,
} from "@/lib/consumerModels/utils";
import { useUser } from "@/providers/UserProvider";

export interface ConsumerModelProfileSelectorProps {
  disabled?: boolean;
}

export default function ConsumerModelProfileSelector({
  disabled = false,
}: ConsumerModelProfileSelectorProps) {
  const [open, setOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const { refreshUser } = useUser();
  const {
    catalog,
    error: catalogError,
    isLoading: isCatalogLoading,
  } = useConsumerModelCatalog();
  const {
    preference,
    isLoading: isPreferenceLoading,
    refetch: refetchPreference,
  } = useConsumerModelPreference();

  const selectedProfile = useMemo(
    () => findConsumerProfile(catalog, preference?.profile_id),
    [catalog, preference?.profile_id]
  );

  const selectedLabel = getConsumerProfileLabel(
    catalog,
    selectedProfile?.id ?? preference?.profile_id
  );

  const isLoading = isCatalogLoading || isPreferenceLoading;

  const handleSelectProfile = useCallback(
    async (profileId: string) => {
      setIsSaving(true);
      try {
        await updateConsumerModelPreference(profileId);
        await refetchPreference();
        await refreshUser();
        setOpen(false);
      } finally {
        setIsSaving(false);
      }
    },
    [refetchPreference, refreshUser]
  );

  if (catalogError) {
    return (
      <SelectButton
        data-testid="consumer-model-profile-selector-unavailable"
        disabled
        icon={SvgSparkle}
        state="empty"
        variant="select-input"
        size="lg"
      >
        模型服务暂不可用
      </SelectButton>
    );
  }

  if (!catalog || catalog.profiles.length === 0) {
    return null;
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild disabled={disabled || isSaving}>
        <SelectButton
          data-testid="consumer-model-profile-selector"
          disabled={disabled || isSaving}
          icon={SvgSparkle}
          state="empty"
          variant="select-input"
          size="lg"
        >
          {selectedLabel}
        </SelectButton>
      </Popover.Trigger>

      <Popover.Content side="top" align="end" width="md">
        <PopoverMenu>
          {isLoading ? (
            [
              <Text key="loading" font="secondary-body" color="text-03">
                加载模型...
              </Text>,
            ]
          ) : (
            catalog.profiles.map((profile) => {
              const selected = profile.id === selectedProfile?.id;
              return (
                <LineItemButton
                  key={profile.id}
                  selectVariant="select-heavy"
                  state={selected ? "selected" : "empty"}
                  icon={(props) => <div {...(props as any)} />}
                  title={profile.label}
                  description={profile.description}
                  onClick={() => handleSelectProfile(profile.id)}
                  rightChildren={
                    selected ? (
                      <div className="flex h-5 items-center">
                        <SvgCheck className="text-action-link-05" size={16} />
                      </div>
                    ) : null
                  }
                  sizePreset="main-ui"
                  rounding="sm"
                />
              );
            })
          )}
        </PopoverMenu>
      </Popover.Content>
    </Popover>
  );
}
