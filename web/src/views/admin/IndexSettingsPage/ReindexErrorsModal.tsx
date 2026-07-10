import Modal from "@/refresh-components/Modal";
import { Table, createTableColumns, Text } from "@opal/components";
import { SvgAlertCircle } from "@opal/icons";
import { useReindexErrors } from "@/lib/indexing/hooks";
import type { ReindexErrorRow } from "@/lib/indexing/interfaces";

const tc = createTableColumns<ReindexErrorRow>();
const COLUMNS = [
  tc.column("scope", {
    header: "Type",
    weight: 15,
    cell: (value) => (value === "connector" ? "Connector" : "User Files"),
  }),
  tc.column("name", { header: "Name", weight: 25 }),
  tc.displayColumn({
    id: "entity_id",
    header: "ID",
    width: { weight: 15 },
    cell: (row) => row.cc_pair_id ?? row.user_id ?? "—",
  }),
  tc.column("error_msg", {
    header: "Error",
    weight: 45,
    cell: (value) => (
      <Text font="secondary-body" color="text-03">
        {value ?? "Unknown error"}
      </Text>
    ),
  }),
];

interface ReindexErrorsModalProps {
  onClose: () => void;
}

export default function ReindexErrorsModal({
  onClose,
}: ReindexErrorsModalProps) {
  const { data: errors, isLoading } = useReindexErrors(true);

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="lg" height="sm">
        <Modal.Header
          icon={SvgAlertCircle}
          title="Re-index Errors"
          description="Connectors and user files whose latest re-index attempt failed."
          onClose={onClose}
        />
        <Modal.Body>
          {isLoading ? (
            <Text as="p" color="text-03">
              Loading…
            </Text>
          ) : !errors || errors.length === 0 ? (
            <Text as="p" color="text-03">
              No re-index errors.
            </Text>
          ) : (
            <Table
              data={errors}
              columns={COLUMNS}
              getRowId={(row) =>
                `${row.scope}-${row.cc_pair_id ?? row.user_id}`
              }
            />
          )}
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
