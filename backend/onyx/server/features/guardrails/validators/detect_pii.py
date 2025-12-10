from presidio_anonymizer.entities import OperatorConfig

from onyx.server.features.guardrails.init_validators import _analyzer, _anonymizer
from onyx.server.features.guardrails.services import generate_fake_data


ENTITY_GENERATORS = {
    "RUS_PERSON": generate_fake_data.generate_fake_rus_person,
    "RUS_PHONE_NUMBER": generate_fake_data.generate_fake_rus_phone_number,
    "RUS_BANK_CARD": generate_fake_data.generate_fake_rus_bank_card,
    "RUS_INN": generate_fake_data.generate_fake_rus_inn,
    "RUS_OGRNIP": generate_fake_data.generate_fake_rus_ogrnip,
    "RUS_SNILS": generate_fake_data.generate_fake_rus_snils,
    "RUS_OMS_POLICY": generate_fake_data.generate_fake_rus_oms_policy,
    "RUS_PASSPORT": generate_fake_data.generate_fake_rus_passport,
    "RUS_DRIVER_LICENSE": generate_fake_data.generate_fake_rus_driver_license,
    "RUS_LOCATION": generate_fake_data.generate_fake_rus_location,
    "EMAIL_ADDRESS": generate_fake_data.generate_fake_email_address,
    "IP_ADDRESS": generate_fake_data.generate_fake_ip_address,
    "DATE_TIME": generate_fake_data.generate_fake_date_time,
    "URL": generate_fake_data.generate_fake_url,
    "DOMAIN_NAME": generate_fake_data.generate_fake_domain_name,
}


def mask_pii(
    text: str,
    config: dict,
) -> tuple[str, dict]:
    """Маскирование данных"""

    mapping = {}
    pii_entities = config.get("pii_entities")

    if not pii_entities:
        return text, mapping

    # Создаем операторы с передачей mapping в функции
    fake_operators = {}

    for entity in pii_entities:
        if ENTITY_GENERATORS.get(entity):
            fake_operators[entity] = OperatorConfig(
                "custom",
                {"lambda": lambda x, entity=entity: ENTITY_GENERATORS[entity](x, mapping)}
            )

    # Анализируем текст
    analysis_results = _analyzer.analyze(
        text=text,
        entities=pii_entities,
        language="en",
    )

    # Маскируем с фейковыми данными
    anonymized_result = _anonymizer.anonymize(
        text=text,
        analyzer_results=analysis_results,
        operators=fake_operators
    )

    return anonymized_result.text, mapping


def unmask_pii(
    llm_response: str,
    mapping: dict[str, str] | None
) -> str:
    """Демаскирование данных"""

    if not mapping:
        return llm_response

    unmasked_text = llm_response

    for fake_value, original_value in mapping.items():
        unmasked_text = unmasked_text.replace(fake_value, original_value)

    return unmasked_text


if __name__=="__main__":
    from onyx.server.features.guardrails.init_validators import initialize_presidio_analyzer
    initialize_presidio_analyzer()

    config = {
        "pii_entities": [
            "EMAIL_ADDRESS",
            "RUS_PHONE_NUMBER",
            "RUS_BANK_CARD",
            "DOMAIN_NAME",
            "IP_ADDRESS",
            "URL",
            "CRYPTO",
        ]

    }
    message = """
    КЛИЕНТСКАЯ ИНФОРМАЦИЯ:
    --------------------
    Email: ivan@mail.ru
    Телефон: 8-800-555-3555
    Домен: smartsearch.ru
    IP-адрес: 192.168.1.1
    Веб-сайт: https://example.com
    Банковская карта: 4276-5500-3444-6289
    Банковская карта мир: 2200 5500 3444 6289
    Crypto wallet: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa
    """

    print(f"Исходное сообщение: {message}")


    masked_message, mapping = mask_pii(text=message, config=config)
    print(f"Маскированное сообщение: {masked_message}")

    unmasked_message = unmask_pii(llm_response=masked_message, mapping=mapping)
    print(f"Демаскированное сообщение: {unmasked_message}")
