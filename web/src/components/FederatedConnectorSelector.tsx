import React, { useState, useRef, useEffect } from "react";
import {
  FederatedConnectorDetail,
  FederatedConnectorConfig,
  federatedSourceToRegularSource,
  ValidSources,
} from "@/lib/types";
import { SourceIcon } from "@/components/SourceIcon";
import { X, Search, Settings } from "lucide-react";
import { Label } from "@/components/ui/label";
import { ErrorMessage } from "formik";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

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

interface EntityConfigDialogProps {
  connectorId: number;
  connectorName: string;
  connectorSource: ValidSources | null;
  currentEntities: Record<string, any>;
  onSave: (entities: Record<string, any>) => void;
  onClose: () => void;
  isOpen: boolean;
}

const EntityConfigDialog = ({
  connectorId,
  connectorName,
  connectorSource,
  currentEntities,
  onSave,
  onClose,
  isOpen,
}: EntityConfigDialogProps) => {
  const [entities, setEntities] =
    useState<Record<string, any>>(currentEntities);
  const [entitySchema, setEntitySchema] = useState<Record<string, any> | null>(
    null
  );
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen && connectorId) {
      const fetchEntitySchema = async () => {
        setIsLoading(true);
        setError(null);
        try {
          const response = await fetch(
            `/api/federated/${connectorId}/entities`
          );
          if (!response.ok) {
            throw new Error(
              `Failed to fetch entity schema: ${response.statusText}`
            );
          }
          const data = await response.json();
          setEntitySchema(data.entities);
        } catch (err) {
          setError(
            err instanceof Error ? err.message : "Failed to load entity schema"
          );
        } finally {
          setIsLoading(false);
        }
      };
      fetchEntitySchema();
    }
  }, [isOpen, connectorId]);

  const handleSave = () => {
    onSave(entities);
    onClose();
  };

  const handleEntityChange = (key: string, value: any) => {
    setEntities((prev) => ({
      ...prev,
      [key]: value,
    }));
  };

  if (!connectorSource) {
    return null;
  }

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <SourceIcon
              sourceType={federatedSourceToRegularSource(connectorSource)}
              iconSize={20}
            />
            Configure {connectorName}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {isLoading && (
            <div className="text-center py-4">
              <div className="animate-spin h-6 w-6 border-2 border-blue-500 border-t-transparent rounded-full mx-auto mb-2"></div>
              <p className="text-sm text-muted-foreground">
                Loading configuration...
              </p>
            </div>
          )}

          {error && (
            <div className="text-red-500 text-sm p-3 bg-red-50 rounded-md">
              {error}
            </div>
          )}

          {entitySchema && !isLoading && (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                Configure which entities to include from this connector:
              </p>

              {Object.entries(entitySchema).map(
                ([key, field]: [string, any]) => (
                  <div key={key} className="space-y-2">
                    <Label className="text-sm font-medium">
                      {field.description || key}
                      {field.required && (
                        <span className="text-red-500 ml-1">*</span>
                      )}
                    </Label>

                    {field.type === "list" ? (
                      <div className="space-y-2">
                        <Input
                          type="text"
                          placeholder={
                            field.example || `Enter ${key} (comma-separated)`
                          }
                          value={
                            Array.isArray(entities[key])
                              ? entities[key].join(", ")
                              : ""
                          }
                          onChange={(e) => {
                            const value = e.target.value;
                            const list = value
                              ? value
                                  .split(",")
                                  .map((item) => item.trim())
                                  .filter(Boolean)
                              : [];
                            handleEntityChange(key, list);
                          }}
                        />
                        <p className="text-xs text-muted-foreground">
                          {field.description && field.description !== key
                            ? field.description
                            : `Enter ${key} separated by commas`}
                        </p>
                      </div>
                    ) : (
                      <div className="space-y-2">
                        <Input
                          type="text"
                          placeholder={field.example || `Enter ${key}`}
                          value={entities[key] || ""}
                          onChange={(e) =>
                            handleEntityChange(key, e.target.value)
                          }
                        />
                        {field.description && field.description !== key && (
                          <p className="text-xs text-muted-foreground">
                            {field.description}
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                )
              )}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-4">
            <Button variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button onClick={handleSave} disabled={isLoading}>
              Save Configuration
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

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
  const [configDialogState, setConfigDialogState] = useState<{
    isOpen: boolean;
    connectorId: number | null;
    connectorName: string;
    connectorSource: ValidSources | null;
    currentEntities: Record<string, any>;
  }>({
    isOpen: false,
    connectorId: null,
    connectorName: "",
    connectorSource: null,
    currentEntities: {},
  });
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

  const openConfigDialog = (connectorId: number) => {
    const connector = federatedConnectors.find((c) => c.id === connectorId);
    const config = selectedConfigs.find(
      (c) => c.federated_connector_id === connectorId
    );

    if (connector) {
      setConfigDialogState({
        isOpen: true,
        connectorId,
        connectorName: connector.name,
        connectorSource: connector.source,
        currentEntities: config?.entities || {},
      });
    }
  };

  const saveEntityConfig = (entities: Record<string, any>) => {
    const updatedConfigs = selectedConfigs.map((config) => {
      if (config.federated_connector_id === configDialogState.connectorId) {
        return {
          ...config,
          entities,
        };
      }
      return config;
    });
    onChange(updatedConfigs);
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

      <p className="text-xs text-neutral-500 dark:text-neutral-400">
        Documents from selected federated connectors will be searched in
        real-time during queries.
      </p>
      <div className="relative">
        <div
          className={`flex items-center border border-input rounded-md border-neutral-200 dark:border-neutral-700 ${
            allConnectorsSelected ? "bg-neutral-50 dark:bg-neutral-800" : ""
          } focus-within:ring-1 focus-within:ring-ring focus-within:border-neutral-400 dark:focus-within:border-neutral-500 transition-colors`}
        >
          <Search className="absolute left-3 h-4 w-4 text-neutral-500 dark:text-neutral-400" />
          <input
            ref={inputRef}
            type="text"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setOpen(true);
            }}
            onFocus={() => {
              if (!allConnectorsSelected) {
                setOpen(true);
              }
            }}
            onKeyDown={handleKeyDown}
            placeholder={effectivePlaceholder}
            className={`h-9 w-full pl-9 pr-10 py-2 bg-transparent dark:bg-transparent text-sm outline-none disabled:cursor-not-allowed disabled:opacity-50 ${
              allConnectorsSelected
                ? "text-neutral-500 dark:text-neutral-400"
                : ""
            }`}
            disabled={isInputDisabled}
          />
        </div>

        {open && !allConnectorsSelected && (
          <div
            ref={dropdownRef}
            className="absolute z-50 w-full mt-1 rounded-md border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 shadow-md default-scrollbar max-h-[300px] overflow-auto"
          >
            {filteredUnselectedConnectors.length === 0 ? (
              <div className="py-4 text-center text-xs text-neutral-500 dark:text-neutral-400">
                {searchQuery
                  ? "No matching federated connectors found"
                  : "No more federated connectors available"}
              </div>
            ) : (
              <div>
                {filteredUnselectedConnectors.map((connector) => (
                  <div
                    key={connector.id}
                    className="flex items-center justify-between py-2 px-3 cursor-pointer hover:bg-neutral-50 dark:hover:bg-neutral-800 text-xs"
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
                  className="flex items-center bg-white dark:bg-neutral-800 rounded-md border border-neutral-300 dark:border-neutral-700 transition-all px-2 py-1 max-w-full group text-xs"
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
                    <button
                      className="flex-shrink-0 rounded-full w-4 h-4 flex items-center justify-center bg-neutral-100 dark:bg-neutral-700 text-neutral-500 dark:text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-600 hover:text-neutral-700 dark:hover:text-neutral-300 transition-colors"
                      onClick={() => openConfigDialog(connector.id)}
                      aria-label="Configure entities"
                      title="Configure entities"
                    >
                      <Settings className="h-2.5 w-2.5" />
                    </button>
                    <button
                      className="flex-shrink-0 rounded-full w-4 h-4 flex items-center justify-center bg-neutral-100 dark:bg-neutral-700 text-neutral-500 dark:text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-600 hover:text-neutral-700 dark:hover:text-neutral-300 transition-colors"
                      onClick={() => removeConnector(connector.id)}
                      aria-label="Remove connector"
                    >
                      <X className="h-2.5 w-2.5" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="mt-3 p-3 border border-dashed border-neutral-300 dark:border-neutral-700 rounded-md bg-neutral-50 dark:bg-neutral-800 text-neutral-500 dark:text-neutral-400 text-xs">
          No federated connectors selected. Search and select connectors above.
        </div>
      )}

      <EntityConfigDialog
        connectorId={configDialogState.connectorId!}
        connectorName={configDialogState.connectorName}
        connectorSource={configDialogState.connectorSource}
        currentEntities={configDialogState.currentEntities}
        onSave={saveEntityConfig}
        onClose={() =>
          setConfigDialogState((prev) => ({ ...prev, isOpen: false }))
        }
        isOpen={configDialogState.isOpen}
      />

      {showError && (
        <ErrorMessage
          name={name}
          component="div"
          className="text-red-500 dark:text-red-400 text-xs mt-1"
        />
      )}
    </div>
  );
};
