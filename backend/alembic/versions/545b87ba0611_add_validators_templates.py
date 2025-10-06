"""add validators templates

Revision ID: 545b87ba0611
Revises: 2b9492e28665
Create Date: 2025-10-06 17:44:02.274840

"""


from alembic import op
import sqlalchemy as sa
from sqlalchemy import table, column
from sqlalchemy.dialects import postgresql

from onyx.db.enums import ValidatorType

# revision identifiers, used by Alembic.
revision = "545b87ba0611"
down_revision = "2b9492e28665"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем в таблицу Validator данные о шаблонах валидаторов

    validator_table = table(
        "validator",
        column("name", sa.String),
        column("description", sa.String),
        column("validator_type", sa.String),
        column("config", postgresql.JSONB),
    )

    op.bulk_insert(
        validator_table,
        [
            {
                "name": "Валидатор персональных данных",
                "description": "Обнаружение и маскирование персональных данных (email, тел. номера, кредитные карты..)",
                "validator_type": ValidatorType.DETECT_PII,
                "config": {
                    "pii_entities": [
                        "EMAIL_ADDRESS",
                        "PHONE_NUMBER",
                        "DOMAIN_NAME",
                        "IP_ADDRESS",
                        "DATE_TIME",
                        "LOCATION",
                        "PERSON",
                        "URL",
                        "CREDIT_CARD",
                        "CRYPTO",
                        "IBAN_CODE",
                        "NRP",
                        "MEDICAL_LICENSE",
                        "US_BANK_NUMBER",
                        "US_DRIVER_LICENSE",
                        "US_ITIN",
                        "US_PASSPORT",
                        "US_SSN",
                    ],
                },
            },
        ]
    )


def downgrade() -> None:
    # Удаление из таблицы Validator данных о шаблонах валидаторов

    op.execute("DELETE FROM validator WHERE user_id IS NULL")
