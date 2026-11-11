"""Onyx-owned load fix-up for ``voyageai/voyage-4-nano``, with no remote code.

A plain SentenceTransformer load of this checkpoint gives wrong vectors and no
error: transformers loads the native, causal ``Qwen3Model`` and drops the
bias-free ``linear.weight`` projection (1024 -> 2048). The checkpoint's remote
code fails on transformers 5.14.1, and Onyx never runs remote code anyway. The
fix makes attention bidirectional and adds the projection as a bias-free
``Dense`` layer after mean pooling: pooling is linear, so this equals the remote
code's per-token projection. Checked on real weights against an independent
re-implementation of the remote model: 1 - cosine < 2e-7.
"""

from typing import TYPE_CHECKING, cast

import torch

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

# The checkpoint file that holds the projection, and the tensor name in it.
VOYAGE_NANO_PROJECTION_FILE = "model.safetensors"
_PROJECTION_WEIGHT_KEY = "linear.weight"


def read_projection_weight(safetensors_path: str) -> torch.Tensor:
    """Read the bias-free projection weight, shape [out_dim, hidden_dim]."""
    from safetensors import safe_open

    with safe_open(safetensors_path, framework="pt") as checkpoint:
        return checkpoint.get_tensor(_PROJECTION_WEIGHT_KEY)


def add_bidirectional_projection(
    model: "SentenceTransformer", projection_weight: torch.Tensor
) -> "SentenceTransformer":
    """Return voyage-4-nano with bidirectional attention and the 2048-dim projection.

    ``model`` is the plain native load (Transformer -> Pooling -> Normalize).
    """
    from sentence_transformers import SentenceTransformer
    from sentence_transformers.base.modules import Transformer
    from sentence_transformers.sentence_transformer.modules import Dense

    transformer, pooling, normalize = model[0], model[1], model[2]
    # The Qwen3 forward reads this on every call. It must be set after the load:
    # Qwen3Config ignores an is_causal config kwarg.
    cast(Transformer, transformer).auto_model.config.is_causal = False

    projection = Dense(
        in_features=projection_weight.shape[1],
        out_features=projection_weight.shape[0],
        bias=False,
        activation_function=None,  # identity
        init_weight=projection_weight,
    )
    return SentenceTransformer(modules=[transformer, pooling, projection, normalize])
