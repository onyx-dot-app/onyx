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

export type EntityType = {
  name: string;
  description: string;
  active: boolean;
};

export function sanitizeKGConfig(raw: KGConfigRaw): KGConfig {
  const coverage_start = new Date(raw.coverage_start);

  return {
    ...raw,
    coverage_start,
  };
}

export function sanitizeKGEntityTypes(
  entityTypes: EntityType[]
): [EntityTypeValues, EntityType[]] {
  const entityTypeMap: EntityTypeValues = {};
  for (const entityType of entityTypes) {
    entityTypeMap[entityType.name.toLowerCase()] = entityType;
  }

  const sortedData = Object.values(entityTypeMap);
  sortedData.sort((a, b) => a.name.localeCompare(b.name));

  return [entityTypeMap, sortedData];
}
