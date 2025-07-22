export type KGConfig = {
  enabled: boolean;
  vendor?: string | null;
  vendor_domains?: string[] | null;
  ignore_domains?: string[] | null;
  coverage_start: Date;
};

export type KGConfigRaw = {
  enabled: boolean;
  vendor?: string | null;
  vendor_domains?: string[] | null;
  ignore_domains?: string[] | null;
  coverage_start: string;
};

export type EntityTypeValues = { [key: string]: EntityType };

export type SourceAndEntityTypeView = {
  source_statistics: Record<string, SourceStatistics>;
  entity_types: Record<string, EntityType[]>;
};

export type SourceStatistics = {
  source_name: string;
  last_updated: string;
  entities_count: number;
};

export type EntityType = {
  name: string;
  description: string;
  active: boolean;
  grounded_source_name: string;
};
