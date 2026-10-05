import React, { useState } from "react";
import { useTranslations } from "next-intl";
import {
  FederatedConnectorDetail,
  FederatedConnectorConfig,
} from "@/lib/types";
import { federatedSourceToRegularSource } from "@/lib/connectors/types/source";
import { SourceIcon } from "@/components/SourceIcon";
import { Label } from "@opal/layouts";
import { ErrorMessage } from "formik";
import Text from "@/refresh-components/texts/Text";
import {
  Button,
  Dropdown,
  InputTypeIn,
  type DropdownMenuItem,
} from "@opal/components";
import { SvgX } from "@opal/icons";
import { cn } from "@opal/utils";

interface FederatedConnectorSelectorProps {
  name: string;
  label: string;
  federatedConnectors: FederatedConnectorDetail[];
  selectedConfigs: FederatedConnectorConfig[];
  onChange: (selectedConfigs: FederatedConnectorConfig[]) => void;
  disabled?: boolean;
  placeholder?: string;
  showError?: boolean;
}

export const FederatedConnectorSelector = ({
  name,
  label,
  federatedConnectors,
  selectedConfigs,
  onChange,
  disabled = false,
  placeholder,
  showError = false,
}: FederatedConnectorSelectorProps) => {
  const t = useTranslations("common.federatedConnectorSelector");
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const selectedConnectorIds = selectedConfigs.map(
    (config) => config.federated_connector_id
  );

  const selectedConnectors = federatedConnectors.filter((connector) =>
    selectedConnectorIds.includes(connector.id)
  );

  const unselectedConnectors = federatedConnectors.filter(
    (connector) => !selectedConnectorIds.includes(connector.id)
  );

  const allConnectorsSelected = unselectedConnectors.length === 0;

  const selectConnector = (connectorId: number) => {
    // Add connector with empty entities configuration
    const newConfig: FederatedConnectorConfig = {
      federated_connector_id: connectorId,
      entities: {},
    };

    onChange([...selectedConfigs, newConfig]);
    setSearchQuery("");
  };

  const removeConnector = (connectorId: number) => {
    onChange(
      selectedConfigs.filter(
        (config) => config.federated_connector_id !== connectorId
      )
    );
  };

  const effectivePlaceholder = allConnectorsSelected
    ? t("allSelected.placeholder")
    : (placeholder ?? t("search.placeholder"));

  const isInputDisabled = disabled || allConnectorsSelected;

  // The unpicked connectors, each a custom row since its title carries an
  // icon; one message row when there is nothing left to pick.
  const items: DropdownMenuItem[] =
    unselectedConnectors.length === 0
      ? [
          {
            kind: "custom",
            id: "message",
            disabled: true,
            pinned: true,
            render: ({ props }) => (
              <div {...props} className="py-4 text-center text-xs text-text-03">
                {t("noMoreConnectors.text")}
              </div>
            ),
          },
        ]
      : unselectedConnectors.map((connector) => ({
          kind: "custom",
          id: String(connector.id),
          keywords: [connector.name],
          onActivate: () => selectConnector(connector.id),
          keepOpen: true,
          render: ({ highlighted, props }) => (
            <div
              {...props}
              aria-label={connector.name}
              className={cn(
                "w-full flex items-center justify-between py-2 px-3 cursor-pointer rounded-08 text-xs",
                highlighted && "bg-background-neutral-01"
              )}
            >
              <div className="flex items-center truncate me-2">
                <div className="me-2">
                  <SourceIcon
                    sourceType={federatedSourceToRegularSource(
                      connector.source
                    )}
                    iconSize={16}
                  />
                </div>
                <span className="font-medium">{connector.name}</span>
              </div>
            </div>
          ),
        }));

  return (
    <div className="flex flex-col w-full space-y-2 mb-4">
      {label && (
        <Label>
          <Text>{label}</Text>
        </Label>
      )}

      <Text as="p" mainUiMuted text03>
        {t("realtimeSearchHint.description")}
      </Text>
      <Dropdown open={open} onOpenChange={setOpen}>
        <Dropdown.Trigger asChild typeIn behavior="open">
          <InputTypeIn
            searchIcon
            placeholder={effectivePlaceholder}
            value={searchQuery}
            variant={isInputDisabled ? "disabled" : undefined}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              // Typing opens the list, as a type-in does.
              setOpen(true);
            }}
          />
        </Dropdown.Trigger>
        <Dropdown.Data
          label={effectivePlaceholder}
          query={searchQuery}
          items={items}
        />
      </Dropdown>

      {selectedConnectors.length > 0 ? (
        <div className="mt-3">
          <div className="flex flex-wrap gap-1.5">
            {selectedConnectors.map((connector) => {
              const config = selectedConfigs.find(
                (c) => c.federated_connector_id === connector.id
              );
              const hasEntitiesConfigured =
                config && Object.keys(config.entities).length > 0;

              return (
                <div
                  key={connector.id}
                  className="flex items-center bg-background-neutral-00 rounded-12 border border-border-02 transition-all px-2 py-1 max-w-full group text-xs"
                >
                  <div className="flex items-center overflow-hidden">
                    <div className="me-1 shrink-0">
                      <SourceIcon
                        sourceType={federatedSourceToRegularSource(
                          connector.source
                        )}
                        iconSize={14}
                      />
                    </div>
                    <span className="font-medium truncate">
                      {connector.name}
                    </span>
                    {hasEntitiesConfigured && (
                      <div
                        className="ms-1 w-2 h-2 bg-green-500 rounded-full shrink-0"
                        title={t("entitiesConfigured.tooltip")}
                      />
                    )}
                  </div>
                  <div className="flex items-center ms-2 gap-1">
                    <Button
                      prominence="tertiary"
                      size="sm"
                      type="button"
                      aria-label={t("removeConnector.tooltip")}
                      tooltip={t("removeConnector.tooltip")}
                      onClick={() => removeConnector(connector.id)}
                      icon={SvgX}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="mt-3 p-3 border border-dashed border-border-02 rounded-12 bg-background-neutral-01 text-text-03 text-xs">
          {t("noneSelected.text")}
        </div>
      )}

      {showError && (
        <ErrorMessage
          name={name}
          component="div"
          className="text-action-danger-05 text-xs mt-1"
        />
      )}
    </div>
  );
};
