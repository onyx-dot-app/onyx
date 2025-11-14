from functools import lru_cache
from os import urandom

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from onyx.configs.app_configs import ENCRYPTION_KEY_SECRET
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation

logger = setup_logger()


@lru_cache(maxsize=1)
def _get_trimmed_key(secret: str) -> bytes:
    """Подготавливает ключ шифрования, обрезая до допустимой длины AES."""
    raw_bytes = secret.encode('utf-8')
    byte_size = len(raw_bytes)
    if byte_size < 16:
        raise RuntimeError("Секретный ключ шифрования слишком короткий")
    if byte_size > 32:
        return raw_bytes[:32]
    if byte_size in (16, 24, 32):
        return raw_bytes
    # Обрезаем до ближайшей стандартной длины
    aes_sizes = [16, 24, 32]
    closest_size = min(aes_sizes, key=lambda size: abs(size - byte_size))
    return raw_bytes[:closest_size]


def _encrypt_string(plain_text: str) -> bytes:
    """Шифрует строку с использованием AES-CBC и PKCS7."""
    if not ENCRYPTION_KEY_SECRET:
        return plain_text.encode('utf-8')

    cipher_key = _get_trimmed_key(ENCRYPTION_KEY_SECRET)
    init_vector = urandom(16)
    data_padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded_plain = data_padder.update(plain_text.encode('utf-8')) + data_padder.finalize()

    crypto_engine = Cipher(algorithms.AES(cipher_key), modes.CBC(init_vector), backend=default_backend())
    data_encryptor = crypto_engine.encryptor()
    ciphered_output = data_encryptor.update(padded_plain) + data_encryptor.finalize()

    return init_vector + ciphered_output


def _decrypt_bytes(ciphered_input: bytes) -> str:
    """Дешифрует байты обратно в строку с удалением padding."""
    if not ENCRYPTION_KEY_SECRET:
        return ciphered_input.decode('utf-8')

    cipher_key = _get_trimmed_key(ENCRYPTION_KEY_SECRET)
    init_vector = ciphered_input[:16]
    ciphered_payload = ciphered_input[16:]

    crypto_engine = Cipher(algorithms.AES(cipher_key), modes.CBC(init_vector), backend=default_backend())
    data_decryptor = crypto_engine.decryptor()
    unpadded_ciphered = data_decryptor.update(ciphered_payload) + data_decryptor.finalize()

    data_unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    clean_output = data_unpadder.update(unpadded_ciphered) + data_unpadder.finalize()

    return clean_output.decode('utf-8')


def encrypt_string_to_bytes(input_str: str) -> bytes:
    impl_encrypt = fetch_versioned_implementation(
        "onyx.utils.encryption", "_encrypt_string"
    )
    return impl_encrypt(input_str)


def decrypt_bytes_to_string(input_bytes: bytes) -> str:
    impl_decrypt = fetch_versioned_implementation(
        "onyx.utils.encryption", "_reverse_byte_decryption"
    )
    return impl_decrypt(input_bytes)


def test_encryption() -> None:
    """Проверяет корректность шифрования/дешифрования на тестовом примере."""
    sample_text = "Onyx is the BEST!"
    ciphered_data = encrypt_string_to_bytes(sample_text)
    recovered_text = decrypt_bytes_to_string(ciphered_data)
    if sample_text != recovered_text:
        raise RuntimeError("Тест шифрования/дешифрования не пройден")

