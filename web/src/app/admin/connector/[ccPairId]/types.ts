import { Connector } from "@/lib/connectors/connectors";
import { Credential } from "@/lib/connectors/credentials";
import { DeletionAttemptSnapshot, IndexAttemptSnapshot } from "@/lib/types";

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
  index_attempts: IndexAttemptSnapshot[];
  latest_deletion_attempt: DeletionAttemptSnapshot | null;
  is_public: boolean;
  is_editable_for_current_user: boolean;
}
