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
  showActions?: boolean;
}

function DisplayModelHeader({
  alternativeText,
  onSelectAll,
  onRefresh,
  showActions = true,
}: DisplayModelHeaderProps) {
  return (
    <GeneralLayouts.Section
      flexDirection="row"
      justifyContent="between"
      alignItems="center"
    >
      <GeneralLayouts.Section gap={0} alignItems="start" width="fit">
        <Text as="p" mainContentEmphasis>
          Models
        </Text>
        <Text as="p" secondaryBody text03>
          {alternativeText ??
            "Select models to make available for this provider."}
        </Text>
      </GeneralLayouts.Section>
      {showActions && (
        <GeneralLayouts.Section flexDirection="row" gap={0.25} width="fit">
          <Button main tertiary onClick={onSelectAll}>
            Select All
          </Button>
          <IconButton
            icon={SvgRefreshCw}
            main
            internal
            onClick={onRefresh}
            tooltip="Refresh models"
          />
        </GeneralLayouts.Section>
      )}
    </GeneralLayouts.Section>
  );
}

interface ModelRowProps {
  modelName: string;
  isSelected: boolean;
  isDefault: boolean;
  onCheckChange: (checked: boolean) => void;
}

function ModelRow({
  modelName,
  isSelected,
  isDefault,
  onCheckChange,
}: ModelRowProps) {
  return (
    <Card
      variant="borderless"
      flexDirection="row"
      justifyContent="between"
      alignItems="center"
      className={"cursor-pointer"}
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
          mainUiAction
          className={cn(
            "select-none",
            isSelected ? "text-action-link-05" : "text-text-03"
          )}
        >
          {modelName}
        </Text>
      </GeneralLayouts.Section>
      {isDefault && (
        <Text as="span" secondaryBody className="text-action-link-05">
          Default Model
        </Text>
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
  displayModelName,
}: {
  formikProps: FormikProps<T>;
  modelConfigurations: ModelConfiguration[];
  noModelConfigurationsMessage?: string;
  isLoading?: boolean;
  shouldShowAutoUpdateToggle: boolean;
  displayModelName: string | null;
}) {
  const [moreModelsOpen, setMoreModelsOpen] = useState(false);
  const isAutoMode = formikProps.values.is_auto_mode;

  if (isLoading) {
    return (
      <GeneralLayouts.Section gap={0.75} alignItems="stretch">
        <DisplayModelHeader showActions={false} />
        <Card padding={0.75}>
          <SimpleLoader />
        </Card>
      </GeneralLayouts.Section>
    );
  }

  const handleCheckboxChange = (modelName: string, checked: boolean) => {
    const currentSelected = formikProps.values.selected_model_names ?? [];

    if (checked) {
      const newSelected = [...currentSelected, modelName];
      formikProps.setFieldValue("selected_model_names", newSelected);
    } else {
      const newSelected = currentSelected.filter((name) => name !== modelName);
      formikProps.setFieldValue("selected_model_names", newSelected);
    }
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
    const aIsDefault = a.name === displayModelName;
    const bIsDefault = b.name === displayModelName;
    const aIsSelected = selectedModels.includes(a.name);
    const bIsSelected = selectedModels.includes(b.name);

    if (aIsDefault && !bIsDefault) return -1;
    if (!aIsDefault && bIsDefault) return 1;
    if (aIsSelected && !bIsSelected) return -1;
    if (!aIsSelected && bIsSelected) return 1;
    return 0;
  });

  if (modelConfigurations.length === 0) {
    return (
      <GeneralLayouts.Section gap={0.75} alignItems="stretch">
        <DisplayModelHeader
          alternativeText={noModelConfigurationsMessage ?? "No models found"}
          showActions={false}
        />
      </GeneralLayouts.Section>
    );
  }

  // For auto mode display
  const visibleModels = modelConfigurations.filter((m) => m.is_visible);

  const primaryAutoModels = visibleModels.filter((m) =>
    selectedModels.includes(m.name)
  );
  const moreAutoModels = visibleModels.filter(
    (m) => !selectedModels.includes(m.name)
  );

  return (
    <GeneralLayouts.Section gap={0.75} alignItems="stretch">
      <DisplayModelHeader
        onSelectAll={handleSelectAll}
        onRefresh={handleRefresh}
      />
      <Card padding={0} gap={0}>
        <Card variant="borderless" gap={0.25}>
          {isAutoMode && shouldShowAutoUpdateToggle ? (
            // Auto mode: read-only display
            <>
              {primaryAutoModels.map((model) => {
                const isDefault = model.name === displayModelName;
                return (
                  <ModelRow
                    key={model.name}
                    modelName={model.name}
                    isSelected={true}
                    isDefault={isDefault}
                    onCheckChange={() => {}}
                  />
                );
              })}

              {moreAutoModels.length > 0 && (
                <Collapsible
                  open={moreModelsOpen}
                  onOpenChange={setMoreModelsOpen}
                >
                  <CollapsibleTrigger asChild>
                    <Card variant="borderless" padding={0}>
                      <MoreModelsButton isOpen={moreModelsOpen} />
                    </Card>
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <GeneralLayouts.Section gap={0.25} alignItems="start">
                      {moreAutoModels.map((model) => {
                        const isDefault = model.name === displayModelName;
                        return (
                          <ModelRow
                            key={model.name}
                            modelName={model.name}
                            isSelected={true}
                            isDefault={isDefault}
                            onCheckChange={() => {}}
                          />
                        );
                      })}
                    </GeneralLayouts.Section>
                  </CollapsibleContent>
                </Collapsible>
              )}
            </>
          ) : (
            // Manual mode: checkbox selection
            <>
              {primaryModels.map((modelConfiguration) => {
                const isSelected = selectedModels.includes(
                  modelConfiguration.name
                );
                const isDefault = displayModelName === modelConfiguration.name;

                return (
                  <ModelRow
                    key={modelConfiguration.name}
                    modelName={modelConfiguration.name}
                    isSelected={isSelected}
                    isDefault={isDefault}
                    onCheckChange={(checked) =>
                      handleCheckboxChange(modelConfiguration.name, checked)
                    }
                  />
                );
              })}

              {moreModels.length > 0 && (
                <Collapsible
                  open={moreModelsOpen}
                  onOpenChange={setMoreModelsOpen}
                >
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
                          displayModelName === modelConfiguration.name;

                        return (
                          <ModelRow
                            key={modelConfiguration.name}
                            modelName={modelConfiguration.name}
                            isSelected={isSelected}
                            isDefault={isDefault}
                            onCheckChange={(checked) =>
                              handleCheckboxChange(
                                modelConfiguration.name,
                                checked
                              )
                            }
                          />
                        );
                      })}
                    </GeneralLayouts.Section>
                  </CollapsibleContent>
                </Collapsible>
              )}
            </>
          )}
        </Card>

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
    </GeneralLayouts.Section>
  );
}
