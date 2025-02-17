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
  ACTIVE = "ACTIVE",
  PAUSED = "PAUSED",
  DELETING = "DELETING",
}

export interface CCPairFullInfo {
  id: number;
  name: string;
  status: ConnectorCredentialPairStatus;
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
