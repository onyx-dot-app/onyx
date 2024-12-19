import { FiTrash, FiX } from "react-icons/fi";
import { BasicClickable } from "@/components/BasicClickable";
import { Modal } from "../Modal";

export const DeleteEntityModal = ({
  onClose,
  onSubmit,
  entityType,
  entityName,
  additionalDetails,
  deleteButtonText,
}: {
  entityType: string;
  entityName: string;
  onClose: () => void;
  onSubmit: () => void;
  additionalDetails?: string;
  deleteButtonText?: string;
}) => {
  return (
    <Modal onOutsideClick={onClose}>
      <>
        <div className="flex mb-4">
          <h2 className="my-auto text-2xl font-bold">
            {deleteButtonText || `Delete`} {entityType}
          </h2>
        </div>
        <p className="mb-4">
          Click below to confirm that you want to {deleteButtonText || "delete"}{" "}
          <b>{entityName}</b>
        </p>
        {additionalDetails && <p className="mb-4">{additionalDetails}</p>}
        <div className="flex">
          <div className="mx-auto">
            <BasicClickable onClick={onSubmit}>
              <div className="flex mx-2">
                <FiTrash className="my-auto mr-2" />
                {deleteButtonText || "Delete"}
              </div>
            </BasicClickable>
          </div>
        </div>
      </>
    </Modal>
  );
};
