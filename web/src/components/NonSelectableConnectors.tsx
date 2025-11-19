import React from "react";
import { ConnectorStatus } from "@/lib/types";
import { ConnectorTitle } from "@/components/admin/connectors/ConnectorTitle";
import { Label } from "@/components/ui/label";
import Text from "@/refresh-components/texts/Text";
import SvgLock from "@/icons/lock";

interface NonSelectableConnectorsProps {
  connectors: ConnectorStatus<any, any>[];
  title: string;
  description: string;
}

export const NonSelectableConnectors = ({
  connectors,
  title,
  description,
}: NonSelectableConnectorsProps) => {
  if (connectors.length === 0) {
    return null;
  }

  return (
    <div className="mt-6 mb-4">
      <Label className="text-base font-medium mb-1">{title}</Label>
      <Text mainUiMuted text03 className="mb-3">
        {description}
      </Text>
      <div className="p-3 border border-dashed border-border-02 rounded-12 bg-background-neutral-01">
        <div className="mb-2 flex items-center gap-1.5">
          <SvgLock className="h-3.5 w-3.5 stroke-text-03" />
          <Text figureSmallLabel text04 className="!mb-0">
            Unavailable connectors:
          </Text>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {connectors.map((connector) => (
            <div
              key={`${connector.connector.id}-${connector.credential.id}`}
              className="flex items-center px-2 py-1 cursor-not-allowed opacity-80 bg-background-neutral-00 border border-border-02 rounded-12 text-xs"
            >
              <div className="flex items-center max-w-[200px] text-xs">
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
      </div>
    </div>
  );
};
