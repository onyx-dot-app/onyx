from sqlalchemy.orm import Session

from onyx.db.models import KGConfig
from onyx.kg.models import KGConfigSettings


def get_kg_enablement(db_session: Session) -> bool:
    check = (
        db_session.query(KGConfig.kg_variable_values)
        .filter(
            KGConfig.kg_variable_name == "KG_ENABLED"
            and KGConfig.kg_variable_values == ["true"]
        )
        .first()
    )
    if check is None:
        return False
    return True


def get_kg_config_settings(db_session: Session) -> KGConfigSettings:
    results = db_session.query(KGConfig).all()

    kg_config_settings = KGConfigSettings()
    for result in results:
        if result.kg_variable_name == "KG_ENABLED":
            kg_config_settings.KG_ENABLED = result.kg_variable_values[0] == "true"
        elif result.kg_variable_name == "KG_VENDOR":
            kg_config_settings.KG_VENDOR = result.kg_variable_values[0]
        elif result.kg_variable_name == "KG_VENDOR_DOMAINS":
            kg_config_settings.KG_VENDOR_DOMAINS = result.kg_variable_values
        elif result.kg_variable_name == "KG_IGNORE_EMAIL_DOMAINS":
            kg_config_settings.KG_IGNORE_EMAIL_DOMAINS = result.kg_variable_values

    if not kg_config_settings.KG_ENABLED:
        kg_config_settings.KG_ENABLED = False

    return kg_config_settings
