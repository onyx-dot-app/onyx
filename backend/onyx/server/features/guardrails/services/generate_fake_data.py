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


def generate_fake_credit_card(original: str, mapping: Dict[str, str]) -> str:
    fake_card = faker.credit_card_number()
    mapping[fake_card] = original
    return fake_card


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


def generate_fake_crypto(original: str, mapping: Dict[str, str]) -> str:
    # Генерируем фейковый crypto wallet address
    crypto_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    fake_crypto = "1" + ''.join(random.choice(crypto_chars) for _ in range(33))
    mapping[fake_crypto] = original
    return fake_crypto
