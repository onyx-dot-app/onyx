import React, { useState, useRef, useEffect } from "react";
import {
  FederatedConnectorDetail,
  FederatedConnectorConfig,
  federatedSourceToRegularSource,
} from "@/lib/types";
import { SourceIcon } from "@/components/SourceIcon";
import { Label } from "@/components/ui/label";
import { ErrorMessage } from "formik";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { SvgX } from "@opal/icons";

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
  placeholder = "Search federated connectors...",
  showError = false,
}: FederatedConnectorSelectorProps) => {
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const dropdownRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

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

  const filteredUnselectedConnectors = unselectedConnectors.filter(
    (connector) => {
      const connectorName = connector.name;
      return connectorName.toLowerCase().includes(searchQuery.toLowerCase());
    }
  );

  useEffect(() => {
    if (allConnectorsSelected && open) {
      setOpen(false);
      inputRef.current?.blur();
      setSearchQuery("");
    }
  }, [allConnectorsSelected, open]);

  const selectConnector = (connectorId: number) => {
    // Add connector with empty entities configuration
    const newConfig: FederatedConnectorConfig = {
      federated_connector_id: connectorId,
      entities: {},
    };

    const newSelectedConfigs = [...selectedConfigs, newConfig];
    onChange(newSelectedConfigs);
    setSearchQuery("");

    const willAllBeSelected =
      federatedConnectors.length === newSelectedConfigs.length;

    if (!willAllBeSelected) {
      setTimeout(() => {
        inputRef.current?.focus();
      }, 0);
    }
  };

  const removeConnector = (connectorId: number) => {
    onChange(
      selectedConfigs.filter(
        (config) => config.federated_connector_id !== connectorId
      )
    );
  };

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node) &&
        inputRef.current !== event.target &&
        !inputRef.current?.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const effectivePlaceholder = allConnectorsSelected
    ? "All federated connectors selected"
    : placeholder;

  const isInputDisabled = disabled || allConnectorsSelected;

  return (
    <div className="flex flex-col w-full space-y-2 mb-4">
      {label && <Label className="text-base font-medium">{label}</Label>}

      <Text as="p" mainUiMuted text03>
        Documents from selected federated connectors will be searched in
        real-time during queries.
      </Text>
      <div className="relative">
        <InputTypeIn
          ref={inputRef}
          leftSearchIcon
          placeholder={effectivePlaceholder}
          value={searchQuery}
          disabled={isInputDisabled}
          onChange={(e) => {
            setSearchQuery(e.target.value);
            setOpen(true);
          }}
          onKeyDown={handleKeyDown}
          onFocus={() => {
            if (!allConnectorsSelected) {
              setOpen(true);
            }
          }}
          className={
            allConnectorsSelected
              ? "rounded-12 bg-background-neutral-01"
              : "rounded-12"
          }
        />

        {open && !allConnectorsSelected && (
          <div
            ref={dropdownRef}
            className="absolute z-50 w-full mt-1 rounded-12 border border-border-02 bg-background-neutral-00 shadow-md default-scrollbar max-h-[300px] overflow-auto"
          >
            {filteredUnselectedConnectors.length === 0 ? (
              <div className="py-4 text-center text-xs text-text-03">
                {searchQuery
                  ? "No matching federated connectors found"
                  : "No more federated connectors available"}
              </div>
            ) : (
              <div>
                {filteredUnselectedConnectors.map((connector) => (
                  <div
                    key={connector.id}
                    className="flex items-center justify-between py-2 px-3 cursor-pointer hover:bg-background-neutral-01 text-xs"
                    onClick={() => selectConnector(connector.id)}
                  >
                    <div className="flex items-center truncate mr-2">
                      <div className="mr-2">
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
                ))}
              </div>
            )}
          </div>
        )}
      </div>

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
                    <div className="mr-1 flex-shrink-0">
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
                        className="ml-1 w-2 h-2 bg-green-500 rounded-full flex-shrink-0"
                        title="Entities configured"
                      />
                    )}
                  </div>
                  <div className="flex items-center ml-2 gap-1">
                    <IconButton
                      internal
                      type="button"
                      aria-label="Remove connector"
                      tooltip="Remove connector"
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
          No federated connectors selected. Search and select connectors above.
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
