export type Values = {
  enabled: boolean;
  vendor: string;
  vendorDomains: string[];
  ignoreDomains: string[];
  coverageStart: Date | null;
  coverageDays: number | null;
};

export type EntityType = {
  name: string;
  description: string;
  active: boolean;
};
