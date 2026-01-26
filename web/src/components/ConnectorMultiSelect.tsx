import React, { useState, useRef, useEffect } from "react";
import { ConnectorStatus } from "@/lib/types";
import { ConnectorTitle } from "@/components/admin/connectors/ConnectorTitle";
import { Label } from "@/components/ui/label";
import { ErrorMessage } from "formik";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgX } from "@opal/icons";
interface ConnectorMultiSelectProps {
  name: string;
  label: string;
  connectors: ConnectorStatus<any, any>[];
  selectedIds: number[];
  onChange: (selectedIds: number[]) => void;
  disabled?: boolean;
  placeholder?: string;
  showError?: boolean;
}

export const ConnectorMultiSelect = ({
  name,
  label,
  connectors,
  selectedIds,
  onChange,
  disabled = false,
  placeholder = "Search connectors...",
  showError = false,
}: ConnectorMultiSelectProps) => {
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const dropdownRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const selectedConnectors = connectors.filter((connector) =>
    selectedIds.includes(connector.cc_pair_id)
  );

  const unselectedConnectors = connectors.filter(
    (connector) => !selectedIds.includes(connector.cc_pair_id)
  );

  const allConnectorsSelected =
    connectors.length > 0 && unselectedConnectors.length === 0;

  const filteredUnselectedConnectors = unselectedConnectors.filter(
    (connector) => {
      const connectorName = connector.name || connector.connector.source;
      return connectorName.toLowerCase().includes(searchQuery.toLowerCase());
    }
  );

  useEffect(() => {
    if (allConnectorsSelected) {
      setSearchQuery("");
    }
  }, [allConnectorsSelected, selectedIds]);

  const selectConnector = (connectorId: number) => {
    const newSelectedIds = [...selectedIds, connectorId];
    onChange(newSelectedIds);
    setSearchQuery("");

    const willAllBeSelected = connectors.length === newSelectedIds.length;

    if (!willAllBeSelected) {
      setTimeout(() => {
        inputRef.current?.focus();
      }, 0);
    }
  };

  const removeConnector = (connectorId: number) => {
    onChange(selectedIds.filter((id) => id !== connectorId));
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
    ? "All connectors selected"
    : placeholder;

  const isInputDisabled = disabled;

  return (
    <div className="flex flex-col w-full space-y-2 mb-4">
      {label && <Label className="text-base font-medium">{label}</Label>}

      <Text as="p" mainUiMuted text03>
        All documents indexed by the selected connectors will be part of this
        document set.
      </Text>
      <div className="relative">
        <InputTypeIn
          ref={inputRef}
          leftSearchIcon
          placeholder={effectivePlaceholder}
          value={searchQuery}
          variant={isInputDisabled ? "disabled" : undefined}
          onChange={(e) => {
            if (!allConnectorsSelected) {
              setSearchQuery(e.target.value);
              setOpen(true);
            }
          }}
          onFocus={() => {
            setOpen(true);
          }}
          onKeyDown={handleKeyDown}
          className="rounded-12"
        />

        {open && (
          <div
            ref={dropdownRef}
            className="absolute z-50 w-full mt-1 rounded-12 border border-border-02 bg-background-neutral-00 shadow-md default-scrollbar max-h-[300px] overflow-auto"
          >
            {allConnectorsSelected ? (
              <div className="py-4 px-3">
                <Text as="p" text03 className="text-center text-xs">
                  All available connectors have been selected. Remove connectors
                  below to add different ones.
                </Text>
              </div>
            ) : filteredUnselectedConnectors.length === 0 ? (
              <div className="py-4 px-3">
                <Text as="p" text03 className="text-center text-xs">
                  {searchQuery
                    ? "No matching connectors found"
                    : connectors.length === 0
                      ? "No private connectors available. Create a private connector first."
                      : "No more connectors available"}
                </Text>
              </div>
            ) : (
              <div>
                {filteredUnselectedConnectors.map((connector) => (
                  <div
                    key={connector.cc_pair_id}
                    className="flex items-center justify-between py-2 px-3 cursor-pointer hover:bg-background-neutral-01 text-xs"
                    onClick={() => selectConnector(connector.cc_pair_id)}
                  >
                    <div className="flex items-center truncate mr-2">
                      <ConnectorTitle
                        connector={connector.connector}
                        ccPairId={connector.cc_pair_id}
                        ccPairName={connector.name}
                        isLink={false}
                        showMetadata={false}
                      />
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
            {selectedConnectors.map((connector) => (
              <div
                key={connector.cc_pair_id}
                className="flex items-center bg-background-neutral-00 rounded-12 border border-border-02 transition-all px-2 py-1 max-w-full group text-xs"
              >
                <div className="flex items-center overflow-hidden">
                  <div className="flex-shrink-0 text-xs">
                    <ConnectorTitle
                      connector={connector.connector}
                      ccPairId={connector.cc_pair_id}
                      ccPairName={connector.name}
                      isLink={false}
                      showMetadata={false}
                    />
                  </div>
                </div>
                <IconButton
                  internal
                  type="button"
                  aria-label="Remove connector"
                  tooltip="Remove connector"
                  onClick={() => removeConnector(connector.cc_pair_id)}
                  icon={SvgX}
                />
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="mt-3 p-3 border border-dashed border-border-02 rounded-12 bg-background-neutral-01 text-text-03 text-xs">
          No connectors selected. Search and select connectors above.
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
