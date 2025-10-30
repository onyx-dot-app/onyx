from faker import Faker
from typing import Dict
import random

faker = Faker(locale="ru_RU")


def generate_fake_rus_phone_number(original: str, mapping: Dict[str, str]) -> str:
    fake_phone = faker.phone_number()
    mapping[fake_phone] = original
    return fake_phone


def generate_fake_email_address(original: str, mapping: Dict[str, str]) -> str:
    fake_email = faker.email()
    mapping[fake_email] = original
    return fake_email


def generate_fake_ip_address(original: str, mapping: Dict[str, str]) -> str:
    fake_ip = faker.ipv4()
    mapping[fake_ip] = original
    return fake_ip


def generate_fake_url(original: str, mapping: Dict[str, str]) -> str:
    fake_url = faker.url()
    mapping[fake_url] = original
    return fake_url


def generate_fake_domain_name(original: str, mapping: Dict[str, str]) -> str:
    fake_domain = faker.domain_name()
    mapping[fake_domain] = original
    return fake_domain


def generate_fake_rus_bank_card(original: str, mapping: Dict[str, str]) -> str:
    fake_rus_bank_card = faker.credit_card_number()
    mapping[fake_rus_bank_card] = original
    return fake_rus_bank_card


def generate_fake_rus_inn(original: str, mapping: Dict[str, str]) -> str:
    fake_rus_inn = faker.businesses_inn()

    if len(original) == 12:
        fake_rus_inn = faker.individuals_inn()

    mapping[fake_rus_inn] = original
    return fake_rus_inn


def generate_fake_rus_passport(original: str, mapping: Dict[str, str]) -> str:
    fake_rus_passport = faker.passport_number()

    mapping[fake_rus_passport] = original
    return fake_rus_passport


def generate_fake_rus_driver_license(original: str, mapping: Dict[str, str]) -> str:
    series_part_1 = random.randint(10, 99)
    series_part_2 = random.randint(10, 99)
    number_part = random.randint(100000, 999999)

    fake_rus_driver_license = f"{series_part_1} {series_part_2} {number_part}"

    mapping[fake_rus_driver_license] = original
    return fake_rus_driver_license


def generate_fake_date_time(original: str, mapping: Dict[str, str]) -> str:
    fake_date_time = faker.date()

    mapping[fake_date_time] = original
    return fake_date_time


def generate_fake_rus_snils(original: str, mapping: Dict[str, str]) -> str:
    fake_rus_snils = faker.snils()

    mapping[fake_rus_snils] = original
    return fake_rus_snils


def generate_fake_rus_ogrnip(original: str, mapping: Dict[str, str]) -> str:
    fake_rus_ogrnip = faker.individuals_ogrn()

    mapping[fake_rus_ogrnip] = original
    return fake_rus_ogrnip


def generate_fake_rus_oms_policy(original: str, mapping: Dict[str, str]) -> str:
    fake_rus_oms_policy = str(random.randint(1000000000000000, 9999999999999999))

    mapping[fake_rus_oms_policy] = original
    return fake_rus_oms_policy


def generate_fake_rus_location(original: str, mapping: Dict[str, str]) -> str:
    fake_location = faker.address()

    mapping[fake_location] = original
    return fake_location


def generate_fake_rus_person(original: str, mapping: Dict[str, str]) -> str:
    fake_rus_person = faker.name()

    mapping[fake_rus_person] = original
    return fake_rus_person
