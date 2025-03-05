import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";

interface InstantSwitchConfirmModalProps {
  onClose: () => void;
  onConfirm: () => void;
}

export const InstantSwitchConfirmModal = ({
  onClose,
  onConfirm,
}: InstantSwitchConfirmModalProps) => {
  return (
    <Modal
      onOutsideClick={onClose}
      width="max-w-3xl"
      title="Are you sure you want to do an instant switch?"
    >
      <>
        <div>
          Instant switching will immediately change the embedding model without
          re-indexing. Searches will be over a partial set of documents
          (starting with 0 documents) until re-indexing is complete.
          <br />
          <br />
          <b>This is not reversible.</b>
        </div>
        <div className="flex mt-4 gap-x-2 justify-end">
          <Button onClick={onConfirm}>Confirm</Button>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </>
    </Modal>
  );
};
