"use client";

import React, { useState, useRef, useEffect } from "react";
import { ConnectorStatus } from "@/lib/types";
import { ConnectorTitle } from "@/components/admin/connectors/ConnectorTitle";
import { Label } from "@opal/layouts";
import { ErrorMessage } from "formik";
import Text from "@/refresh-components/texts/Text";
import { InputTypeIn } from "@opal/components";
import { SvgX } from "@opal/icons";
import { Button } from "@opal/components";

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
  placeholder = "搜索连接器...",
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
    ? "已选择全部连接器"
    : placeholder;

  const isInputDisabled = disabled;

  return (
    <div className="flex flex-col w-full space-y-2 mb-4">
      {label && (
        <Label>
          <Text>{label}</Text>
        </Label>
      )}

      <Text as="p" mainUiMuted text03>
        所选连接器已索引的全部文档都会纳入此文档集。
      </Text>
      <div className="relative">
        <InputTypeIn
          ref={inputRef}
          searchIcon
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
        />

        {open && (
          <div
            ref={dropdownRef}
            className="absolute z-50 w-full mt-1 rounded-12 border border-border-02 bg-background-neutral-00 shadow-md default-scrollbar max-h-[300px] overflow-auto"
          >
            {allConnectorsSelected ? (
              <div className="py-4 px-3">
                <Text as="p" text03 className="text-center text-xs">
                  已选择全部可用连接器。移除下方连接器后可添加其他连接器。
                </Text>
              </div>
            ) : filteredUnselectedConnectors.length === 0 ? (
              <div className="py-4 px-3">
                <Text as="p" text03 className="text-center text-xs">
                  {searchQuery
                    ? "未找到匹配的连接器"
                    : connectors.length === 0
                      ? "暂无可用的私有连接器，请先创建一个私有连接器。"
                      : "没有更多可用连接器"}
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
                  <div className="shrink-0 text-xs">
                    <ConnectorTitle
                      connector={connector.connector}
                      ccPairId={connector.cc_pair_id}
                      ccPairName={connector.name}
                      isLink={false}
                      showMetadata={false}
                    />
                  </div>
                </div>
                <Button
                  prominence="tertiary"
                  size="sm"
                  type="button"
                  aria-label="移除连接器"
                  tooltip="移除连接器"
                  onClick={() => removeConnector(connector.cc_pair_id)}
                  icon={SvgX}
                />
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="mt-3 p-3 border border-dashed border-border-02 rounded-12 bg-background-neutral-01 text-text-03 text-xs">
          尚未选择连接器。请在上方搜索并选择连接器。
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
