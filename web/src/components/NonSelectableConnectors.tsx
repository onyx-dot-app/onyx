import React from "react";
import { ConnectorStatus } from "@/lib/types";
import { ConnectorTitle } from "@/components/admin/connectors/ConnectorTitle";
import { Label } from "@/components/ui/label";
import { LockIcon } from "lucide-react";

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
      <p className="text-xs text-neutral-500 mb-3">{description}</p>
      <div className="p-3 border border-dashed border-neutral-300 rounded-md bg-neutral-50">
        <div className="text-xs font-medium text-neutral-700 mb-2 flex items-center">
          <LockIcon className="h-3.5 w-3.5 mr-1.5 text-neutral-500" />
          Unavailable connectors:
        </div>
        <div className="flex flex-wrap gap-1.5">
          {connectors.map((connector) => (
            <div
              key={`${connector.connector.id}-${connector.credential.id}`}
              className="flex items-center px-2 py-1 cursor-not-allowed opacity-80 bg-white border border-neutral-300 rounded-md text-xs"
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
