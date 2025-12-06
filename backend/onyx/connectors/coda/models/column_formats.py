from enum import StrEnum
from typing import List
from typing import Literal
from typing import Optional

from pydantic import Field
from pydantic.main import BaseModel

from onyx.connectors.coda.models.table import CodaTableReference


class CodaColumnFormatType(StrEnum):
    """
    Represents the valid string values for the layout type of a table or view.
    """

    TEXT = "text"
    PERSON = "person"
    LOOKUP = "lookup"
    NUMBER = "number"
    PERCENT = "percent"
    CURRENCY = "currency"
    DATE = "date"
    DATETIME = "datetime"
    TIME = "time"
    DURATION = "duration"
    SLIDER = "slider"
    SCALE = "scale"
    IMAGE = "image"
    IMAGE_REFERENCE = "imageReference"
    ATTACHMENTS = "attachments"
    BUTTON = "button"
    CHECKBOX = "checkbox"
    SELECT = "select"
    PACK_OBJECT = "packObject"
    CANVAS = "canvas"
    OTHER = "other"


class CodaSimpleColumnFormat(BaseModel):
    """Format of a simple column"""

    type: CodaColumnFormatType
    isArray: bool


class CodaNumericColumnFormat(CodaSimpleColumnFormat):
    """Format of a numeric column"""

    type: Literal[CodaColumnFormatType.number]
    precision: Optional[int] = Field(ge=0, le=10)
    useThousandsSeparator: Optional[bool]


class CodaButtonColumnFormat(CodaSimpleColumnFormat):
    """Format of a button column"""

    type: Literal[CodaColumnFormatType.button]
    label: Optional[str] = Field(
        description="Label formula for the button.", example="Click me"
    )
    disableIf: Optional[str] = Field(
        description="Formula to disable the button.", example="False()"
    )
    action: Optional[str] = Field(
        description="Action formula for the button.",
        example='OpenUrl("www.google.com")',
    )


class CodaDateColumnFormat(CodaSimpleColumnFormat):
    """Format of a date column"""

    type: Literal[CodaColumnFormatType.date]
    format: Optional[str] = Field(
        description="A format string using Moment syntax: https://momentjs.com/docs/#/displaying/",
        example="YYYY-MM-DD",
    )


class CodaCheckboxDisplayType(StrEnum):
    TOGGLE = "toggle"
    TEXT = "text"


class CodaCheckboxColumnFormat(CodaSimpleColumnFormat):
    """Format of a checkbox column"""

    type: Literal[CodaColumnFormatType.checkbox]
    displayType: CodaCheckboxDisplayType = Field(
        description="Display type for the checkbox column.", example="text"
    )


class CodaDateTimeColumnFormat(CodaSimpleColumnFormat):
    """Format of a date column."""

    type: Literal[CodaColumnFormatType.datetime]
    dateFormat: Optional[str] = Field(
        description="A format string using Moment syntax: https://momentjs.com/docs/#/displaying/",
        example="YYYY-MM-DD",
    )
    timeFormat: Optional[str] = Field(
        description="A format string using Moment syntax: https://momentjs.com/docs/#/displaying/",
        example="HH:mm:ss",
    )


class CodaDurationUnit(StrEnum):
    DAYS = "days"
    HOURS = "hours"
    MINUTES = "minutes"
    SECONDS = "seconds"


class CodaDurationColumnFormat(CodaSimpleColumnFormat):
    """Format of a duration column."""

    type: Literal[CodaColumnFormatType.duration]
    precision: Optional[int] = Field(ge=0, le=10)
    maxUnit: Optional[CodaDurationUnit] = Field(
        description="Maximum unit for the duration column.", example="days"
    )


class CodaEmailDisplayType(StrEnum):
    ICON_AND_EMAIL = "IconAndEmail"
    ICON_ONLY = "IconOnly"
    EMAIL_ONLY = "EmailOnly"


class CodaEmailColumnFormat(CodaSimpleColumnFormat):
    """Format of an email column."""

    type: Literal[CodaColumnFormatType.email]
    display: Optional[Literal[CodaEmailDisplayType]]
    autocomplete: Optional[bool]


class CodaCurrencyFormatType(StrEnum):
    """How the numeric value should be formatted (with or without symbol, negative numbers in parens)."""

    CURRENCY = "currency"
    ACCOUNTING = "accounting"
    FINANCIAL = "financial"


class CodaCurrencyColumnFormat(CodaSimpleColumnFormat):
    """Format of a currency column."""

    type: Literal[CodaColumnFormatType.currency]
    currencyCode: Optional[str] = Field(
        description="Currency code for the currency column.", example="$"
    )
    precision: Optional[int] = Field(
        description="Decimal precision for the currency column.", example=2, ge=0, le=10
    )
    format: Optional[CodaCurrencyFormatType]


class CodaNumberOrNumberFormula(BaseModel):
    """A number or a string representing a formula that evaluates to a number."""

    int | str


class CodaImageReferenceStyle(StrEnum):
    """How the numeric value should be formatted (with or without symbol, negative numbers in parens)."""

    AUTO = "auto"
    CIRCLE = "circle"


class CodaImageReferenceColumnFormat(CodaSimpleColumnFormat):
    """Format of an image reference column."""

    type: Literal[CodaColumnFormatType.image_reference]
    width: CodaNumberOrNumberFormula
    height: CodaNumberOrNumberFormula
    style: Optional[CodaImageReferenceStyle]


class CodaReferenceColumnFormat(CodaSimpleColumnFormat):
    """Format of a column that refers to another table."""

    type: Literal[CodaColumnFormatType.reference]
    table: CodaTableReference


class CodaSelectOption(BaseModel):
    """An option in a select column."""

    name: str = Field(description="The name of the option.")
    backgroundColor: Optional[str] = Field(
        description="The background color of the option.", example="#FF0000"
    )
    foregroundColor: Optional[str] = Field(
        description="The foreground color of the option.", example="#FFFFFF"
    )


class CodaSelectColumnFormat(CodaSimpleColumnFormat):
    """Format of a select column."""

    type: Literal[CodaColumnFormatType.select]
    options: Optional[List[CodaSelectOption]] = Field(
        description="Only returned for select lists that used a fixed set of options. Returns the first 5000 options"
    )


class CodaImageReferenceStyle(StrEnum):
    """How the numeric value should be formatted (with or without symbol, negative numbers in parens)."""

    STAR = "star"
    FIRE = "fire"
    BUG = "bug"
    DIAMOND = "diamond"
    BEL = "bell"
    THUMBSUP = "thumbsup"
    HEART = "heart"
    CHILI = "chili"
    SMILEY = "smiley"
    LIGHTNING = "lightning"
    CURRENCY = "currency"
    COFFEE = "coffee"
    PERSON = "person"
    BATTERY = "battery"
    COCKTAIL = "cocktail"
    CLOUD = "cloud"
    SUN = "sun"
    CHECKMARK = "checkmark"
    LIGHTBULB = "lightbulb"


class CodaScaleColumnFormat(CodaSimpleColumnFormat):
    """Format of a numeric column that renders as a scale, like star ratings."""

    type: Literal[CodaColumnFormatType.scale]
    maximum: Optional[int] = Field(
        description="The maximum number allowed for this scale.", example=5
    )


class CodaSliderDisplayType(StrEnum):
    """How the slider should be rendered."""

    SLIDER = "slider"
    PROGRESS = "progress"


class CodaSliderColumnFormat(CodaSimpleColumnFormat):
    """Format of a numeric column that renders as a slider."""

    type: Literal[CodaColumnFormatType.slider]
    minimum: Optional[CodaNumberOrNumberFormula] = Field(
        description="The minimum number allowed for this slider.", example=0
    )
    maximum: Optional[CodaNumberOrNumberFormula] = Field(
        description="The maximum number allowed for this slider.", example=100
    )
    step: Optional[CodaNumberOrNumberFormula] = Field(
        description="The step size increment for this slider.", example=1
    )
    displayType: Optional[CodaSliderDisplayType] = Field(
        description="How the slider should be rendered.", example="slider"
    )
    showValue: Optional[bool] = Field(
        description="Whether the underyling numeric value is also displayed.",
        example=True,
    )


class CodaTimeColumnFormat(CodaSimpleColumnFormat):
    """Format of a time column."""

    type: Literal[CodaColumnFormatType.time]
    format: Optional[str] = Field(
        description="A format string using Moment syntax: https://momentjs.com/docs/#/displaying/",
        example="h:mm:ss A",
    )


class CodaTextColumnFormat(CodaSimpleColumnFormat):
    """Format of a text column."""

    type: Literal[CodaColumnFormatType.text]


class CodaNumberColumnFormat(CodaNumericColumnFormat):
    """Format of a number column."""

    type: Literal[CodaColumnFormatType.number]


class CodaPersonColumnFormat(CodaReferenceColumnFormat):
    """Format of a person column."""

    type: Literal[CodaColumnFormatType.person]


class CodaLookupColumnFormat(CodaReferenceColumnFormat):
    """Format of a lookup column."""

    type: Literal[CodaColumnFormatType.lookup]


class CodaPercentageColumnFormat(CodaNumericColumnFormat):
    """Format of a percentage column."""

    type: Literal[CodaColumnFormatType.percentage]


class CodaImageColumnFormat(CodaSimpleColumnFormat):
    """Format of an image column."""

    type: Literal[CodaColumnFormatType.image]


class CodaAttachmentColumnFormat(CodaSimpleColumnFormat):
    """Format of an attachment column."""

    type: Literal[CodaColumnFormatType.attachment]


class CodaPackObjectColumnFormat(CodaSimpleColumnFormat):
    """Format of a pack object column."""

    type: Literal[CodaColumnFormatType.pack_object]


class CodaCanvasColumnFormat(CodaSimpleColumnFormat):
    """Format of a canvas column."""

    type: Literal[CodaColumnFormatType.canvas]


class CodaOtherColumnFormat(CodaSimpleColumnFormat):
    """Format of an other column."""

    type: Literal[CodaColumnFormatType.other]
