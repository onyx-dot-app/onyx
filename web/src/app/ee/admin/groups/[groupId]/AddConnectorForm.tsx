import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../../i18n/keys";
import { Button } from "@/components/Button";
import { Modal } from "@/components/Modal";
import { useState } from "react";
import { FiX } from "react-icons/fi";
import { updateUserGroup } from "./lib";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { ConnectorStatus, UserGroup } from "@/lib/types";
import { ConnectorTitle } from "@/components/admin/connectors/ConnectorTitle";
import { Connector } from "@/lib/connectors/connectors";
import { ConnectorMultiSelect } from "@/components/ConnectorMultiSelect";
import { Form } from "formik";

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
  const { t } = useTranslation();
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
      title={t(k.ADD_NEW_CONNECTOR)}
      onOutsideClick={() => onClose()}
    >
      <div className="px-6 pt-4">
        <ConnectorMultiSelect
          name="connectors"
          label={t(k.SELECT_CONNECTORS)}
          connectors={availableCCPairs}
          selectedIds={selectedCCPairIds}
          onChange={setSelectedCCPairIds}
          placeholder={t(k.SEARCH_CONNECTORS_TO_ADD)}
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
                message: t(k.SUCCESSFULLY_ADDED_CONNECTORS),
                type: "success",
              });
              onClose();
            } else {
              const responseJson = await response.json();
              const errorMsg = responseJson.detail || responseJson.message;
              setPopup({
                message: `${t(k.FAILED_TO_ADD_CONNECTORS_TO_GR)} ${errorMsg}`,
                type: "error",
              });
              onClose();
            }
          }}
        >
          {t(k.ADD_CONNECTORS)}
        </Button>
      </div>
    </Modal>
  );
};
