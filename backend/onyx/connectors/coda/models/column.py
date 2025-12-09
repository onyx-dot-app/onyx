from typing import Annotated
from typing import Literal
from typing import Optional
from typing import Union

from pydantic import Field
from pydantic.main import BaseModel

from onyx.connectors.coda.models.column_formats import CodaAttachmentColumnFormat
from onyx.connectors.coda.models.column_formats import CodaButtonColumnFormat
from onyx.connectors.coda.models.column_formats import CodaCanvasColumnFormat
from onyx.connectors.coda.models.column_formats import CodaCheckboxColumnFormat
from onyx.connectors.coda.models.column_formats import CodaCurrencyColumnFormat
from onyx.connectors.coda.models.column_formats import CodaDateColumnFormat
from onyx.connectors.coda.models.column_formats import CodaDateTimeColumnFormat
from onyx.connectors.coda.models.column_formats import CodaDurationColumnFormat
from onyx.connectors.coda.models.column_formats import CodaImageColumnFormat
from onyx.connectors.coda.models.column_formats import CodaImageReferenceColumnFormat
from onyx.connectors.coda.models.column_formats import CodaLookupColumnFormat
from onyx.connectors.coda.models.column_formats import CodaNumberColumnFormat
from onyx.connectors.coda.models.column_formats import CodaOtherColumnFormat
from onyx.connectors.coda.models.column_formats import CodaPackObjectColumnFormat
from onyx.connectors.coda.models.column_formats import CodaPercentageColumnFormat
from onyx.connectors.coda.models.column_formats import CodaPersonColumnFormat
from onyx.connectors.coda.models.column_formats import CodaScaleColumnFormat
from onyx.connectors.coda.models.column_formats import CodaSelectColumnFormat
from onyx.connectors.coda.models.column_formats import CodaSliderColumnFormat
from onyx.connectors.coda.models.column_formats import CodaTextColumnFormat
from onyx.connectors.coda.models.column_formats import CodaTimeColumnFormat
from onyx.connectors.coda.models.common import CodaObjectType


class CodaColumn(BaseModel):
    """Represents a Coda Table Column"""

    id: str = Field(description="The ID of the column", example="c-tuVwxYz")
    type: Literal[CodaObjectType.COLUMN] = Field(
        description="The type of this resource"
    )
    href: str = Field(
        description="API link to the column",
        example="https://coda.io/apis/v1/docs/AbCDeFGH/tables/grid-pqRst-U/columns/c-tuVwxYz",
    )
    name: str = Field(description="Name of the column.", example="Completed")
    display: Optional[bool] = Field(
        description="Whether the column is displayed in the table.", example=True
    )
    calculated: Optional[bool] = Field(
        description="Whether the column has a formula set on it.", example=True
    )
    formula: Optional[str] = Field(
        description="Formula for the column.", example="thisRow.Created()"
    )
    defaultValue: Optional[str] = Field(
        description="Default value for the column.", example="Test"
    )
    format: Annotated[
        Union[
            CodaTextColumnFormat,
            CodaPersonColumnFormat,
            CodaLookupColumnFormat,
            CodaNumberColumnFormat,
            CodaPercentageColumnFormat,
            CodaCurrencyColumnFormat,
            CodaDateColumnFormat,
            CodaDateTimeColumnFormat,
            CodaTimeColumnFormat,
            CodaDurationColumnFormat,
            CodaSliderColumnFormat,
            CodaScaleColumnFormat,
            CodaImageColumnFormat,
            CodaImageReferenceColumnFormat,
            CodaAttachmentColumnFormat,
            CodaButtonColumnFormat,
            CodaCheckboxColumnFormat,
            CodaSelectColumnFormat,
            CodaPackObjectColumnFormat,
            CodaCanvasColumnFormat,
            CodaOtherColumnFormat,
        ],
        Field(discriminator="type"),
    ]
