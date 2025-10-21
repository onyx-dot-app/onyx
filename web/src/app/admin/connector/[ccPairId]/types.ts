import { Connector } from "@/lib/connectors/connectors";
import { Credential } from "@/lib/connectors/credentials";
import {
  DeletionAttemptSnapshot,
  IndexAttemptSnapshot,
  ValidStatuses,
  AccessType,
} from "@/lib/types";
import { UUID } from "crypto";

export enum ConnectorCredentialPairStatus {
  SCHEDULED = "SCHEDULED",
  INITIAL_INDEXING = "INITIAL_INDEXING",
  ACTIVE = "ACTIVE",
  PAUSED = "PAUSED",
  DELETING = "DELETING",
  INVALID = "INVALID",
}

export enum PermissionSyncStatusEnum {
  CANCELED = "canceled",
  COMPLETED_WITH_ERRORS = "completed_with_errors",
  FAILED = "failed",
  IN_PROGRESS = "in_progress",
  NOT_STARTED = "not_started",
  SUCCESS = "success",
}

/**
 * Returns true if the status is not currently active (i.e. paused or invalid), but not deleting
 */
export function statusIsNotCurrentlyActive(
  status: ConnectorCredentialPairStatus
): boolean {
  return (
    status === ConnectorCredentialPairStatus.PAUSED ||
    status === ConnectorCredentialPairStatus.INVALID
  );
}

export interface CCPairFullInfo {
  id: number;
  name: string;
  status: ConnectorCredentialPairStatus;
  in_repeated_error_state: boolean;
  num_docs_indexed: number;
  connector: Connector<any>;
  credential: Credential<any>;
  number_of_index_attempts: number;
  last_index_attempt_status: ValidStatuses | null;
  latest_deletion_attempt: DeletionAttemptSnapshot | null;
  access_type: AccessType;
  is_editable_for_current_user: boolean;
  deletion_failure_message: string | null;
  indexing: boolean;
  creator: UUID | null;
  creator_email: string | null;

  last_indexed: string | null;
  last_pruned: string | null;
  last_full_permission_sync: string | null;
  overall_indexing_speed: number | null;
  latest_checkpoint_description: string | null;

  // permission sync attempt status
  last_permission_sync_attempt_status: PermissionSyncStatusEnum | null;
  permission_syncing: boolean;
  last_permission_sync_attempt_finished: string | null;
  last_permission_sync_attempt_error_message: string | null;
}

export interface PaginatedIndexAttempts {
  index_attempts: IndexAttemptSnapshot[];
  page: number;
  total_pages: number;
}

export interface IndexAttemptError {
  id: number;
  connector_credential_pair_id: number;

  document_id: string | null;
  document_link: string | null;

  entity_id: string | null;
  failed_time_range_start: string | null;
  failed_time_range_end: string | null;

  failure_message: string;
  is_resolved: boolean;

  time_created: string;

  index_attempt_id: number;
}

export interface PaginatedIndexAttemptErrors {
  items: IndexAttemptError[];
  total_items: number;
}
