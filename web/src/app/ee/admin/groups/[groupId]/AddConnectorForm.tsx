import { Button } from "@/components/Button";
import { Modal } from "@/components/Modal";
import { useState } from "react";
import { updateUserGroup } from "./lib";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { ConnectorStatus, UserGroup } from "@/lib/types";
import { ConnectorMultiSelect } from "@/components/ConnectorMultiSelect";

interface AddConnectorFormProps {
  ccPairs: ConnectorStatus<any, any>[];
  userGroup: UserGroup;
  onClose: () => void;
  setPopup: (popupSpec: PopupSpec) => void;
}

export const AddConnectorForm: React.FC<AddConnectorFormProps> = ({
  ccPairs,
  userGroup,
  onClose,
  setPopup,
}) => {
  const [selectedCCPairIds, setSelectedCCPairIds] = useState<number[]>([]);

  // Filter out ccPairs that are already in the user group and are not private
  const availableCCPairs = ccPairs
    .filter(
      (ccPair) =>
        !userGroup.cc_pairs
          .map((userGroupCCPair) => userGroupCCPair.id)
          .includes(ccPair.cc_pair_id)
    )
    .filter((ccPair) => ccPair.access_type === "private");

  return (
    <Modal
      className="max-w-3xl"
      title="Add New Connector"
      onOutsideClick={() => onClose()}
    >
      <div className="px-6 pt-4">
        <ConnectorMultiSelect
          name="connectors"
          label="Select Connectors"
          connectors={availableCCPairs}
          selectedIds={selectedCCPairIds}
          onChange={setSelectedCCPairIds}
          placeholder="Search for connectors to add..."
          showError={false}
        />

        <Button
          className="mt-4 flex-nowrap w-48"
          onClick={async () => {
            const newCCPairIds = [
              ...Array.from(
                new Set(
                  userGroup.cc_pairs
                    .map((ccPair) => ccPair.id)
                    .concat(selectedCCPairIds)
                )
              ),
            ];
            const response = await updateUserGroup(userGroup.id, {
              user_ids: userGroup.users.map((user) => user.id),
              cc_pair_ids: newCCPairIds,
            });
            if (response.ok) {
              setPopup({
                message: "Successfully added connectors to group",
                type: "success",
              });
              onClose();
            } else {
              const responseJson = await response.json();
              const errorMsg = responseJson.detail || responseJson.message;
              setPopup({
                message: `Failed to add connectors to group - ${errorMsg}`,
                type: "error",
              });
              onClose();
            }
          }}
        >
          Add Connectors
        </Button>
      </div>
    </Modal>
  );
};
