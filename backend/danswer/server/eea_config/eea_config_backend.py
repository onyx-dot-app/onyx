from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from danswer.server.eea_config.models import Config_EEA
from danswer.utils.logger import setup_logger
from danswer.auth.users import current_user, current_admin_user
logger = setup_logger()

#from danswer.dynamic_configs.factory import get_dynamic_config_store
from danswer.key_value_store.factory import get_kv_store
from danswer.key_value_store.interface import KvKeyNotFoundError
from fastapi import HTTPException
from typing import cast
from fastapi import Request

from danswer.db.models import User

EEA_CONFIG_STORAGE_KEY = "eea_custom_config"

router = APIRouter(prefix="/eea_config")

@router.get("/get_eea_config")
def get_eea_config(
#    _: User | None = Depends(current_user),
):
    try:
        return Config_EEA(
            config=cast(
                str, get_kv_store().load(EEA_CONFIG_STORAGE_KEY)
            )
        )
    except KvKeyNotFoundError:
        logger.info("Config Not Found")
        return Config_EEA(config='{}')


@router.post("/set_eea_config")
def set_eea_config(
    request: Config_EEA,
    _: User | None = Depends(current_admin_user),
):
    get_kv_store().store(EEA_CONFIG_STORAGE_KEY, request.config)

    return {"Status":"OK"}
