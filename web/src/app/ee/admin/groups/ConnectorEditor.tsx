import { ConnectorIndexingStatus, ConnectorStatus } from "@/lib/types";
import { ConnectorTitle } from "@/components/admin/connectors/ConnectorTitle";

interface ConnectorEditorProps {
  selectedCCPairIds: number[];
  setSetCCPairIds: (ccPairId: number[]) => void;
  allCCPairs: ConnectorStatus<any, any>[];
}

export const ConnectorEditor = ({
  selectedCCPairIds,
  setSetCCPairIds,
  allCCPairs,
}: ConnectorEditorProps) => {
  return (
    <div className="mb-3 flex gap-2 flex-wrap">
      {allCCPairs
        // remove public docs, since they don't make sense as part of a group
        .filter((ccPair) => !(ccPair.access_type === "public"))
        .map((ccPair) => {
          const ind = selectedCCPairIds.indexOf(ccPair.cc_pair_id);
          const isSelected = ind !== -1;
          return (
            <div
              key={`${ccPair.connector.id}-${ccPair.credential.id}`}
              className={
                `
          px-3 
          py-1
          rounded-lg 
          border
          border-border 
          w-fit 
          flex 
          cursor-pointer ` +
                (isSelected ? " bg-hover" : " hover:bg-hover-light")
              }
              onClick={() => {
                if (isSelected) {
                  setSetCCPairIds(
                    selectedCCPairIds.filter(
                      (ccPairId) => ccPairId !== ccPair.cc_pair_id
                    )
                  );
                } else {
                  setSetCCPairIds([...selectedCCPairIds, ccPair.cc_pair_id]);
                }
              }}
            >
              <div className="my-auto">
                <ConnectorTitle
                  connector={ccPair.connector}
                  ccPairId={ccPair.cc_pair_id}
                  ccPairName={ccPair.name}
                  isLink={false}
                  showMetadata={false}
                />
              </div>
            </div>
          );
        })}
    </div>
  );
};
