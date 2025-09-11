import i18n from "@/i18n/init";
import k from "../../../../i18n/keys";
import { ConnectorStatus } from "@/lib/types";
import { ConnectorMultiSelect } from "@/components/ConnectorMultiSelect";

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
  // Filter out public docs, since they don't make sense as part of a group
  const privateCCPairs = allCCPairs.filter(
    (ccPair) => ccPair.access_type === "private"
  );

  return (
    <ConnectorMultiSelect
      name="connectors"
      label={i18n.t(k.CONNECTORS_LABEL)}
      connectors={privateCCPairs}
      selectedIds={selectedCCPairIds}
      onChange={setSetCCPairIds}
      placeholder={i18n.t(k.SEARCH_CONNECTORS_PLACEHOLDER)}
      showError={true}
    />
  );
};
