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
    "pii_entities": [
      "EMAIL_ADDRESS",
      "PHONE_NUMBER",
      "CREDIT_CARD"
    ]
  },
  created_at: string;
  updated_at: string;
}

export interface APIKeyArgs {
  name?: string;
  description?: string;
  config: any;
}
