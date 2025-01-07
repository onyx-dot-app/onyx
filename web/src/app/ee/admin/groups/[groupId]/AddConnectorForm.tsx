import { Button } from "@/components/Button";
import { SearchMultiSelectDropdown } from "@/components/Dropdown";
import { Modal } from "@/components/Modal";
import { useState } from "react";
import { FiPlus, FiX } from "react-icons/fi";
import { updateUserGroup } from "./lib";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { ConnectorStatus, UserGroup } from "@/lib/types";
import { ConnectorTitle } from "@/components/admin/connectors/ConnectorTitle";
import { Connector } from "@/lib/connectors/connectors";
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

  const selectedCCPairs = ccPairs.filter((ccPair) =>
    selectedCCPairIds.includes(ccPair.cc_pair_id)
  );
  return (
    <Modal title="Add New Connector" onOutsideClick={() => onClose()}>
      <div className="px-6 pt-4 pb-12">
        <div className="mb-2 flex flex-wrap gap-x-2">
          {selectedCCPairs.length > 0 &&
            selectedCCPairs.map((ccPair) => (
              <div
                key={ccPair.cc_pair_id}
                onClick={() => {
                  setSelectedCCPairIds(
                    selectedCCPairIds.filter(
                      (ccPairId) => ccPairId !== ccPair.cc_pair_id
                    )
                  );
                }}
                className={`
                  flex 
                  rounded-lg 
                  px-2 
                  py-1
                  my-1 
                  border 
                  border-border 
                  hover:bg-hover 
                  cursor-pointer`}
              >
                <ConnectorTitle
                  ccPairId={ccPair.cc_pair_id}
                  ccPairName={ccPair.name}
                  connector={ccPair.connector}
                  isLink={false}
                  showMetadata={false}
                />
                <FiX className="ml-1 my-auto" />
              </div>
            ))}
        </div>

        <div className="flex">
          <SearchMultiSelectDropdown
            options={ccPairs
              .filter(
                (ccPair) =>
                  !selectedCCPairIds.includes(ccPair.cc_pair_id) &&
                  !userGroup.cc_pairs
                    .map((userGroupCCPair) => userGroupCCPair.id)
                    .includes(ccPair.cc_pair_id)
              )
              // remove public docs, since they don't make sense as part of a group
              .filter((ccPair) => !(ccPair.access_type === "public"))
              .map((ccPair) => {
                return {
                  name: ccPair.name?.toString() || "",
                  value: ccPair.cc_pair_id?.toString(),
                  metadata: {
                    ccPairId: ccPair.cc_pair_id,
                    connector: ccPair.connector,
                  },
                };
              })}
            onSelect={(option) => {
              setSelectedCCPairIds([
                ...Array.from(
                  new Set([
                    ...selectedCCPairIds,
                    parseInt(option.value as string),
                  ])
                ),
              ]);
            }}
            itemComponent={({ option }) => (
              <div className="flex px-4 py-2.5 hover:bg-hover cursor-pointer">
                <div className="my-auto">
                  <ConnectorTitle
                    ccPairId={option?.metadata?.ccPairId as number}
                    ccPairName={option.name}
                    connector={option?.metadata?.connector as Connector<any>}
                    isLink={false}
                    showMetadata={false}
                  />
                </div>
                <div className="ml-auto my-auto">
                  <FiPlus />
                </div>
              </div>
            )}
          />
          <Button
            className="ml-3 flex-nowrap w-48"
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
                  message: "Successfully added users to group",
                  type: "success",
                });
                onClose();
              } else {
                const responseJson = await response.json();
                const errorMsg = responseJson.detail || responseJson.message;
                setPopup({
                  message: `Failed to add users to group - ${errorMsg}`,
                  type: "error",
                });
                onClose();
              }
            }}
          >
            Add Connectors
          </Button>
        </div>
      </div>
    </Modal>
  );
};
