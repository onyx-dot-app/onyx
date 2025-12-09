import Button from "@/refresh-components/buttons/Button";
import Modal from "@/refresh-components/Modal";
import { useState } from "react";
import { updateUserGroup } from "./lib";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { ConnectorStatus, UserGroup } from "@/lib/types";
import { ConnectorMultiSelect } from "@/components/ConnectorMultiSelect";
import SvgPlus from "@/icons/plus";

export interface AddConnectorFormProps {
  ccPairs: ConnectorStatus<any, any>[];
  userGroup: UserGroup;
  onClose: () => void;
  setPopup: (popupSpec: PopupSpec) => void;
}

export default function AddConnectorForm({
  ccPairs,
  userGroup,
  onClose,
  setPopup,
}: AddConnectorFormProps) {
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
    <Modal open onOpenChange={onClose}>
      <Modal.Content small>
        <Modal.Header
          icon={SvgPlus}
          title="Add New Connector"
          onClose={onClose}
        />
        <Modal.Body>
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
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
