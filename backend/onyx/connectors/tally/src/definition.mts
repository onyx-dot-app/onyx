interface connectionConfig {
    technology: string;
    server: string;
    port: number;
    schema: string;
    ssl: boolean;
    username: string;
    password: string;
    loadmethod: string;
}

interface queryResult {
    rowCount: number;
    data: any[];
}

interface tallyConfig {
    definition: string;
    server: string;
    port: number;
    fromdate: string; // [ YYYYMMDD / auto ]
    todate: string; // [ YYYYMMDD / auto ]
    sync: string; // [ full / incremental ]
    frequency: number; // in minutes
    company: string;
}

interface fieldConfigYAML {
    name: string;
    field: string;
    type: string;
}

interface tableFieldYAML {
    table: string;
    field: string;
}

interface tableConfigYAML {
    name: string;
    collection: string;
    nature: string;
    fields: fieldConfigYAML[];
    filters?: string[];
    fetch?: string[];
    cascade_update?: tableFieldYAML[];
    cascade_delete?: tableFieldYAML[];
}

interface databaseFieldInfo {
    fieldName: string;
    dataType: string;
    isNullable: boolean;
    length?: number;
    precision?: number;
    scale?: number;
}

interface cdmFileFormatSetting {
    $type: string;
    columnHeaders: boolean;
}

interface cdmAttribute {
    name: string;
    dataType: string;
}

interface cdmPartition {
    name: string;
    location: string;
    fileFormatSettings: cdmFileFormatSetting;
}

interface cdmEntity {
    $type: string;
    name: string;
    attributes: cdmAttribute[];
    partitions: cdmPartition[];
}

interface cdmModel {
    name: string;
    version: string;
    entities: cdmEntity[];
}

export { connectionConfig, queryResult, tallyConfig, fieldConfigYAML, tableFieldYAML, tableConfigYAML, databaseFieldInfo, cdmModel, cdmEntity, cdmPartition, cdmAttribute, cdmFileFormatSetting };