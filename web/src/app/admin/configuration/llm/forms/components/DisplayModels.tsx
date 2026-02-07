import { ModelConfiguration, SimpleKnownModel } from "../../interfaces";
import { FormikProps } from "formik";
import { BaseLLMFormValues } from "../formUtils";
import { useState } from "react";

import Checkbox from "@/refresh-components/inputs/Checkbox";
import Switch from "@/refresh-components/inputs/Switch";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";
import { Card } from "@/refresh-components/cards";
import Separator from "@/refresh-components/Separator";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { SvgChevronDown, SvgRefreshCw } from "@opal/icons";
import { cn } from "@/lib/utils";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/refresh-components/Collapsible";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { SvgEmpty } from "@opal/icons";

interface AutoModeToggleProps {
  isAutoMode: boolean;
  onToggle: () => void;
}

function AutoModeToggle({ isAutoMode, onToggle }: AutoModeToggleProps) {
  return (
    <GeneralLayouts.Section
      flexDirection="row"
      justifyContent="between"
      alignItems="center"
    >
      <GeneralLayouts.Section gap={0.125} alignItems="start" width="fit">
        <GeneralLayouts.Section
          flexDirection="row"
          gap={0.375}
          alignItems="center"
          width="fit"
        >
          <Text as="span" mainUiAction>
            Auto Update
          </Text>
          <Text as="span" secondaryBody text03>
            (Recommended)
          </Text>
        </GeneralLayouts.Section>
        <Text as="p" secondaryBody text03>
          Update the available models when new models are released.
        </Text>
      </GeneralLayouts.Section>
      <Switch checked={isAutoMode} onCheckedChange={onToggle} />
    </GeneralLayouts.Section>
  );
}

interface DisplayModelHeaderProps {
  alternativeText?: string;
  onSelectAll?: () => void;
  onRefresh?: () => void;
  isAutoMode: boolean;
  showSelectAll?: boolean;
}

function DisplayModelHeader({
  alternativeText,
  onSelectAll,
  onRefresh,
  isAutoMode,
  showSelectAll = true,
}: DisplayModelHeaderProps) {
  return (
    <GeneralLayouts.Section
      flexDirection="row"
      justifyContent="between"
      alignItems="center"
    >
      <GeneralLayouts.Section gap={0} alignItems="start" width="fit">
        <Text as="p" mainContentBody>
          Models
        </Text>
        <Text as="p" secondaryBody text03>
          {alternativeText ??
            "Select models to make available for this provider."}
        </Text>
      </GeneralLayouts.Section>
      <GeneralLayouts.Section flexDirection="row" gap={0.25} width="fit">
        {showSelectAll && (
          <Button main tertiary onClick={onSelectAll} disabled={isAutoMode}>
            Select All
          </Button>
        )}
        <IconButton
          icon={SvgRefreshCw}
          main
          internal
          onClick={onRefresh}
          tooltip="Refresh models"
        />
      </GeneralLayouts.Section>
    </GeneralLayouts.Section>
  );
}

interface ModelRowProps {
  modelName: string;
  modelDisplayName?: string;
  isSelected: boolean;
  isDefault: boolean;
  onCheckChange: (checked: boolean) => void;
  onSetDefault?: () => void;
}

function ModelRow({
  modelName,
  modelDisplayName,
  isSelected,
  isDefault,
  onCheckChange,
  onSetDefault,
}: ModelRowProps) {
  return (
    <Card
      variant="borderless"
      flexDirection="row"
      justifyContent="between"
      alignItems="center"
      className={cn("cursor-pointer group hover:bg-background-tint-01")}
      padding={0.25}
      onClick={() => onCheckChange(!isSelected)}
    >
      <GeneralLayouts.Section
        flexDirection="row"
        gap={0.75}
        alignItems="center"
        width="fit"
      >
        <Checkbox
          checked={isSelected}
          onCheckedChange={(checked) => onCheckChange(checked)}
          onClick={(e) => e.stopPropagation()}
        />
        <Text
          as="span"
          className={cn(
            "select-none",
            isSelected ? "text-action-link-04" : "text-text-03"
          )}
        >
          {modelDisplayName ?? modelName}
        </Text>
      </GeneralLayouts.Section>
      {isDefault ? (
        <Text as="span" secondaryBody className="text-action-link-05">
          Default Model
        </Text>
      ) : (
        onSetDefault && (
          <Button
            main
            tertiary
            className="opacity-0 group-hover:opacity-100 transition-opacity"
            onClick={(e) => {
              e.stopPropagation();
              onSetDefault();
            }}
          >
            <Text text03>Set as Default</Text>
          </Button>
        )
      )}
    </Card>
  );
}

interface MoreModelsButtonProps {
  isOpen: boolean;
}

function MoreModelsButton({ isOpen }: MoreModelsButtonProps) {
  return (
    <Button
      main
      internal
      transient
      leftIcon={SvgChevronDown}
      className={cn(
        "[&_svg]:transition-transform [&_svg]:duration-200",
        isOpen && "[&_svg]:rotate-180"
      )}
    >
      <Text as="span" text02>
        More Models
      </Text>
    </Button>
  );
}

export function DisplayModels<T extends BaseLLMFormValues>({
  formikProps,
  modelConfigurations,
  noModelConfigurationsMessage,
  isLoading,
  shouldShowAutoUpdateToggle,
}: {
  formikProps: FormikProps<T>;
  modelConfigurations: ModelConfiguration[];
  noModelConfigurationsMessage?: string;
  isLoading?: boolean;
  shouldShowAutoUpdateToggle: boolean;
}) {
  const [moreModelsOpen, setMoreModelsOpen] = useState(false);
  const isAutoMode = formikProps.values.is_auto_mode;
  const defaultModelName = formikProps.values.default_model_name;

  const handleCheckboxChange = (modelName: string, checked: boolean) => {
    if (!checked && modelName === defaultModelName) {
      return;
    }

    const currentSelected = formikProps.values.selected_model_names ?? [];

    if (checked) {
      const newSelected = [...currentSelected, modelName];
      formikProps.setFieldValue("selected_model_names", newSelected);
    } else {
      const newSelected = currentSelected.filter((name) => name !== modelName);
      formikProps.setFieldValue("selected_model_names", newSelected);
    }
  };

  const onSetDefault = (modelName: string) => {
    formikProps.setFieldValue("default_model_name", modelName);
  };

  const handleToggleAutoMode = () => {
    formikProps.setFieldValue("is_auto_mode", !isAutoMode);
    formikProps.setFieldValue(
      "selected_model_names",
      modelConfigurations.filter((m) => m.is_visible).map((m) => m.name)
    );
  };

  const handleSelectAll = () => {
    const allModelNames = modelConfigurations.map((m) => m.name);
    formikProps.setFieldValue("selected_model_names", allModelNames);
  };

  const handleRefresh = () => {
    // Trigger a refresh of models - this would need to be wired up to your fetch logic
    // For now, this is a placeholder
  };

  const selectedModels = formikProps.values.selected_model_names ?? [];

  // Sort models: default first, then selected, then unselected
  const primaryModels = modelConfigurations.filter((m) =>
    selectedModels.includes(m.name)
  );
  const moreModels = modelConfigurations.filter(
    (m) => !selectedModels.includes(m.name)
  );

  const sortedModelConfigurations = [...modelConfigurations].sort((a, b) => {
    const aIsDefault = a.name === defaultModelName;
    const bIsDefault = b.name === defaultModelName;
    const aIsSelected = selectedModels.includes(a.name);
    const bIsSelected = selectedModels.includes(b.name);

    if (aIsDefault && !bIsDefault) return -1;
    if (!aIsDefault && bIsDefault) return 1;
    if (aIsSelected && !bIsSelected) return -1;
    if (!aIsSelected && bIsSelected) return 1;
    return 0;
  });

  // For auto mode display
  const visibleModels = modelConfigurations.filter((m) => m.is_visible);

  const primaryAutoModels = visibleModels.filter((m) =>
    selectedModels.includes(m.name)
  );
  const moreAutoModels = visibleModels.filter(
    (m) => !selectedModels.includes(m.name)
  );

  return (
    <Card variant="borderless">
      <DisplayModelHeader
        onSelectAll={handleSelectAll}
        onRefresh={handleRefresh}
        showSelectAll={modelConfigurations.length > 0}
        isAutoMode={isAutoMode}
      />
      {modelConfigurations.length > 0 ? (
        <Card variant="borderless" padding={0} gap={0}>
          {isAutoMode && shouldShowAutoUpdateToggle ? (
            // Auto mode: read-only display
            <>
              {primaryAutoModels.map((model) => {
                const isDefault = model.name === defaultModelName;
                return (
                  <ModelRow
                    key={model.name}
                    modelName={model.name}
                    modelDisplayName={model.display_name}
                    isSelected={true}
                    isDefault={isDefault}
                    onCheckChange={() => {}}
                  />
                );
              })}
            </>
          ) : (
            // Manual mode: checkbox selection
            <>
              {primaryModels.map((modelConfiguration) => {
                const isSelected = selectedModels.includes(
                  modelConfiguration.name
                );
                const isDefault = defaultModelName === modelConfiguration.name;

                return (
                  <ModelRow
                    key={modelConfiguration.name}
                    modelName={modelConfiguration.name}
                    modelDisplayName={modelConfiguration.display_name}
                    isSelected={isSelected}
                    isDefault={isDefault}
                    onCheckChange={(checked) =>
                      handleCheckboxChange(modelConfiguration.name, checked)
                    }
                    onSetDefault={
                      onSetDefault
                        ? () => onSetDefault(modelConfiguration.name)
                        : undefined
                    }
                  />
                );
              })}
            </>
          )}

          {moreModels.length > 0 && (
            <Collapsible open={moreModelsOpen} onOpenChange={setMoreModelsOpen}>
              <CollapsibleTrigger asChild>
                <Card variant="borderless" padding={0}>
                  <MoreModelsButton isOpen={moreModelsOpen} />
                </Card>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <GeneralLayouts.Section gap={0.25} alignItems="start">
                  {moreModels.map((modelConfiguration) => {
                    const isSelected = selectedModels.includes(
                      modelConfiguration.name
                    );
                    const isDefault =
                      defaultModelName === modelConfiguration.name;

                    return (
                      <ModelRow
                        key={modelConfiguration.name}
                        modelName={modelConfiguration.name}
                        modelDisplayName={modelConfiguration.display_name}
                        isSelected={isSelected}
                        isDefault={isDefault}
                        onCheckChange={(checked) =>
                          handleCheckboxChange(modelConfiguration.name, checked)
                        }
                        onSetDefault={() =>
                          onSetDefault(modelConfiguration.name)
                        }
                      />
                    );
                  })}
                </GeneralLayouts.Section>
              </CollapsibleContent>
            </Collapsible>
          )}

          {/* Auto update toggle */}
          {shouldShowAutoUpdateToggle && (
            <Card variant="borderless" padding={0.75} gap={0.75}>
              <Separator noPadding />
              <AutoModeToggle
                isAutoMode={isAutoMode}
                onToggle={handleToggleAutoMode}
              />
            </Card>
          )}
        </Card>
      ) : (
        <Card variant="tertiary">
          <GeneralLayouts.Section
            gap={0.5}
            flexDirection="row"
            alignItems="center"
            justifyContent="start"
          >
            <SvgEmpty className="w-4 h-4 line-item-icon-muted" />
            <Text text03 secondaryBody>
              {noModelConfigurationsMessage ?? "No models found"}
            </Text>
          </GeneralLayouts.Section>
        </Card>
      )}
    </Card>
  );
}
