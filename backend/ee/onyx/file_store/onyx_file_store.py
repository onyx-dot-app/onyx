from sqlalchemy.orm import Session

from ee.onyx.server.enterprise_settings.store import _LOGO_FILENAME
from ee.onyx.server.enterprise_settings.store import _LOGOTYPE_FILENAME
from onyx.file_store.onyx_file_store import OnyxFileStore
from onyx.utils.file import OnyxFile


class OnyxEnterpriseFileStore(OnyxFileStore):
    def get_logo(self) -> OnyxFile:
        return self.get_db_image(_LOGO_FILENAME)

    def get_logotype(self) -> OnyxFile:
        return self.get_db_image(_LOGOTYPE_FILENAME)


def get_onyx_file_store(db_session: Session) -> OnyxFileStore:
    return OnyxEnterpriseFileStore(db_session=db_session)
