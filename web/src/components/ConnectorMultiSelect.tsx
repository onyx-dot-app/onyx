import React, { useState, useRef, useEffect } from "react";
import { ConnectorStatus } from "@/lib/types";
import { ConnectorTitle } from "@/components/admin/connectors/ConnectorTitle";
import { X, Search } from "lucide-react";
import { Label } from "@/components/ui/label";
import { ErrorMessage } from "formik";

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

  const allConnectorsSelected = unselectedConnectors.length === 0;

  const filteredUnselectedConnectors = unselectedConnectors.filter(
    (connector) => {
      const connectorName = connector.name || connector.connector.source;
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

  useEffect(() => {
    if (allConnectorsSelected) {
      inputRef.current?.blur();
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

  const isInputDisabled = disabled || allConnectorsSelected;

  return (
    <div className="flex flex-col w-full space-y-2 mb-4">
      {label && <Label className="text-base font-medium">{label}</Label>}

      <p className="text-xs text-neutral-500 dark:text-neutral-400">
        All documents indexed by the selected connectors will be part of this
        document set.
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
                  ? "No matching connectors found"
                  : "No more connectors available"}
              </div>
            ) : (
              <div>
                {filteredUnselectedConnectors.map((connector) => (
                  <div
                    key={connector.cc_pair_id}
                    className="flex items-center justify-between py-2 px-3 cursor-pointer hover:bg-neutral-50 dark:hover:bg-neutral-800 text-xs"
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
                className="flex items-center bg-white dark:bg-neutral-800 rounded-md border border-neutral-300 dark:border-neutral-700 transition-all px-2 py-1 max-w-full group text-xs"
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
                <button
                  className="ml-1 flex-shrink-0 rounded-full w-4 h-4 flex items-center justify-center bg-neutral-100 dark:bg-neutral-700 text-neutral-500 dark:text-neutral-400 hover:bg-neutral-200 dark:hover:bg-neutral-600 hover:text-neutral-700 dark:hover:text-neutral-300 transition-colors group-hover:bg-neutral-200 dark:group-hover:bg-neutral-600"
                  onClick={() => removeConnector(connector.cc_pair_id)}
                  aria-label="Remove connector"
                >
                  <X className="h-2.5 w-2.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="mt-3 p-3 border border-dashed border-neutral-300 dark:border-neutral-700 rounded-md bg-neutral-50 dark:bg-neutral-800 text-neutral-500 dark:text-neutral-400 text-xs">
          No connectors selected. Search and select connectors above.
        </div>
      )}

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
