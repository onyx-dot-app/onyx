import struct

import pytest


@pytest.fixture(scope="function")
def test_embedding() -> list[float]:
    # Each value is narrowed to float32 then back to float64 so it survives the
    # cache's float32 packing exactly — tests can assert with `==` instead of
    # tolerating rounding via pytest.approx.
    raw = [0.5, -0.5, 0.25, 0.1, -0.2, 3.4, 0.0, 1e-3]
    return [struct.unpack("<f", struct.pack("<f", v))[0] for v in raw]
