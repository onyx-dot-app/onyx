export interface ConsumerModelProfile {
  id: string;
  label: string;
  description: string;
  supports_image: boolean;
}

export interface ConsumerModelCatalog {
  default_profile_id: string;
  profiles: ConsumerModelProfile[];
}

export interface ConsumerModelPreference {
  profile_id: string;
}
