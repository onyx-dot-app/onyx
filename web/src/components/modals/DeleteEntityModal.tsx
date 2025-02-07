import { FiTrash, FiX } from "react-icons/fi";
import { BasicClickable } from "@/components/BasicClickable";
import { Modal } from "../Modal";
import { Button } from "../ui/button";

export const DeleteEntityModal = ({
  onClose,
  onSubmit,
  entityType,
  entityName,
  additionalDetails,
  deleteButtonText,
  includeCancelButton = true,
}: {
  entityType: string;
  entityName: string;
  onClose: () => void;
  onSubmit: () => void;
  additionalDetails?: string;
  deleteButtonText?: string;
  includeCancelButton?: boolean;
}) => {
  return (
    <Modal width="rounded max-w-sm w-full" onOutsideClick={onClose}>
      <>
        <div className="flex mb-4">
          <h2 className="my-auto text-2xl font-bold">
            {deleteButtonText || `Delete`} {entityType}
          </h2>
        </div>
        <p className="mb-4">
          Are you sure you want to {deleteButtonText || "delete"}{" "}
          <b>{entityName}</b>?
        </p>
        {additionalDetails && <p className="mb-4">{additionalDetails}</p>}
        <div className="flex items-end justify-end">
          <div className="flex gap-x-2">
            {includeCancelButton && (
              <Button variant="outline" onClick={onClose}>
                <div className="flex mx-2">Cancel</div>
              </Button>
            )}
            <Button size="sm" variant="destructive" onClick={onSubmit}>
              <div className="flex mx-2">{deleteButtonText || "Delete"}</div>
            </Button>
          </div>
        </div>
      </>
    </Modal>
  );
};
