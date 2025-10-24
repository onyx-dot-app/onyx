import { UserRole } from "@/lib/types";

export interface APIKey {
  owner: {
    id: string;
    email: string;
  };
  id: number;
  name: string;
  description: string;
  validator_type: "DETECT_PII";
  config: {
    pii_entities: ["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD"];
  };
  include_llm?: boolean;
  llm_provider_id?: number;
  llm_provider?: {
    id: number;
    name: string;
    provider: string;
    default_model_name: string;
    model_names: string[];
  };
  created_at: string;
  updated_at: string;
}

export interface APIKeyArgs {
  name?: string;
  description?: string;
  config: any;
  llm_provider_id?: number;
}
