from __future__ import annotations

from dataclasses import dataclass

from backend.logging_utils import getLogger  # same logger module

logger = getLogger(__name__)


@dataclass(frozen=True)
class CryptoAddresses:
    eth_evm: str
    btc: str
    solana_like: str


CRYPTO_ADDRESSES = CryptoAddresses(
    eth_evm="0x59e7778EB7c28ea6Eb2fE1a06fF693A04E9535Eb",
    btc="bc1p6a9de8md64psxdmu6cjstfzqrxr0rxyxgtyj5293aajlrkpua2ns84ggpr",
    solana_like="BTyjtayJJNguYoBpVDMfrBJgZ25vVZsG96TYwJLf7Wi3",
)


def get_crypto_addresses() -> CryptoAddresses:
    logger.info("Returning crypto payment addresses")
    return CRYPTO_ADDRESSES
