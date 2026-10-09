"use client";

import React, { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { ConnectorStatus } from "@/lib/types";
import { ConnectorTitle } from "@/components/admin/connectors/ConnectorTitle";
import { Label } from "@opal/layouts";
import { ErrorMessage } from "formik";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@opal/utils";
import {
  Button,
  Dropdown,
  InputTypeIn,
  type DropdownMenuItem,
} from "@opal/components";
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
  placeholder,
  showError = false,
}: ConnectorMultiSelectProps) => {
  const t = useTranslations("common.connectorMultiSelect");
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const selectedConnectors = connectors.filter((connector) =>
    selectedIds.includes(connector.cc_pair_id)
  );

  const unselectedConnectors = connectors.filter(
    (connector) => !selectedIds.includes(connector.cc_pair_id)
  );

  const allConnectorsSelected =
    connectors.length > 0 && unselectedConnectors.length === 0;

  useEffect(() => {
    if (allConnectorsSelected) {
      setSearchQuery("");
    }
  }, [allConnectorsSelected, selectedIds]);

  const selectConnector = (connectorId: number) => {
    onChange([...selectedIds, connectorId]);
    setSearchQuery("");
  };

  const removeConnector = (connectorId: number) => {
    onChange(selectedIds.filter((id) => id !== connectorId));
  };

  const effectivePlaceholder = allConnectorsSelected
    ? t("allSelected.placeholder")
    : (placeholder ?? t("search.placeholder"));

  const isInputDisabled = disabled;

  // One message row when there is nothing to pick; else the unpicked
  // connectors, each a custom row since its title is a component.
  const message = allConnectorsSelected
    ? t("allSelected.description")
    : unselectedConnectors.length === 0
      ? connectors.length === 0
        ? t("noPrivateConnectors.text")
        : t("noMoreConnectors.text")
      : undefined;
  const items: DropdownMenuItem[] =
    message !== undefined
      ? [
          {
            kind: "custom",
            id: "message",
            disabled: true,
            pinned: true,
            render: ({ props }) => (
              <div {...props} className="py-4 px-3">
                <Text as="p" text03 className="text-center text-xs">
                  {message}
                </Text>
              </div>
            ),
          },
        ]
      : unselectedConnectors.map((connector) => ({
          kind: "custom",
          id: String(connector.cc_pair_id),
          keywords: [connector.name || connector.connector.source],
          onActivate: () => selectConnector(connector.cc_pair_id),
          keepOpen: true,
          render: ({ highlighted, props }) => (
            <div
              {...props}
              className={cn(
                "w-full flex items-center justify-between py-2 px-3 cursor-pointer rounded-08 text-xs",
                highlighted && "bg-background-neutral-01"
              )}
            >
              <div className="flex items-center truncate me-2">
                <ConnectorTitle
                  connector={connector.connector}
                  ccPairId={connector.cc_pair_id}
                  ccPairName={connector.name}
                  isLink={false}
                  showMetadata={false}
                />
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
        {t("documentSetHint.description")}
      </Text>
      <Dropdown open={open} onOpenChange={setOpen}>
        <Dropdown.Trigger asChild typeIn behavior="open">
          <InputTypeIn
            searchIcon
            placeholder={effectivePlaceholder}
            value={searchQuery}
            variant={isInputDisabled ? "disabled" : undefined}
            onChange={(e) => {
              if (allConnectorsSelected) return;
              setSearchQuery(e.target.value);
              // Typing opens the list, as a type-in does.
              setOpen(true);
            }}
            data-testid="connector-search-input"
          />
        </Dropdown.Trigger>
        <Dropdown.Data
          label={effectivePlaceholder}
          query={searchQuery}
          items={items}
          noMatchText={t("noMatches.text")}
        />
      </Dropdown>

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
                  aria-label={t("removeConnector.tooltip")}
                  tooltip={t("removeConnector.tooltip")}
                  onClick={() => removeConnector(connector.cc_pair_id)}
                  icon={SvgX}
                />
              </div>
            ))}
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
