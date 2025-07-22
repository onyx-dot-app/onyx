from datetime import datetime

from pydantic import ConfigDict
from pydantic.main import BaseModel

from onyx.db.models import KGEntityType
from onyx.kg.models import KGConfigSettings


class KGConfig(BaseModel):
    enabled: bool
    vendor: str | None
    vendor_domains: list[str] | None
    ignore_domains: list[str] | None
    coverage_start: datetime | None

    @classmethod
    def from_kg_config_settings(
        cls,
        kg_config_settings: KGConfigSettings,
    ) -> "KGConfig":
        return cls(
            enabled=kg_config_settings.KG_ENABLED,
            vendor=kg_config_settings.KG_VENDOR,
            vendor_domains=kg_config_settings.KG_VENDOR_DOMAINS,
            ignore_domains=kg_config_settings.KG_IGNORE_EMAIL_DOMAINS,
            coverage_start=kg_config_settings.KG_COVERAGE_START_DATE,
        )


class EnableKGConfigRequest(BaseModel):
    vendor: str
    vendor_domains: list[str]
    ignore_domains: list[str] = []
    coverage_start: datetime

    model_config = ConfigDict(
        extra="forbid",
    )


class DisableKGConfigRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )


class EntityType(BaseModel):
    name: str
    description: str
    active: bool
    grounded_source_name: str | None = None

    @classmethod
    def from_model(
        cls,
        model: KGEntityType,
    ) -> "EntityType":
        return cls(
            name=model.id_name,
            description=model.description or "",
            active=model.active,
            grounded_source_name=model.grounded_source_name,
        )


class SourceStatistics(BaseModel):
    source_name: str
    last_updated: datetime
    entities_count: int


class SourceAndEntityTypeView(BaseModel):
    source_statistics: dict[str, SourceStatistics]
    entity_types: dict[str, list[EntityType]]
