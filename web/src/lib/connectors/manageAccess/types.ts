// Mirrors `ConnectorManageRole` in backend/onyx/db/enums.py.
export type ConnectorManageRole = "editor" | "operator";

// Mirrors `CCPairManageAccessEntry` in backend/onyx/server/documents/models.py.
export interface CCPairManageAccessEntry {
  group_id: number;
  role: ConnectorManageRole;
}

// Mirrors `CCPairManageAccessRow` in backend/ee/onyx/server/documents/manage_access.py.
export interface CCPairManageAccessRow {
  group_id: number;
  group_name: string;
  role: ConnectorManageRole;
  /** Granted by a global Manage Connectors grant: not stored, cannot be removed. */
  is_fixed: boolean;
}
