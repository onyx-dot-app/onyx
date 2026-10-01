"""Onyx-owned load fix-up for ``voyageai/voyage-4-nano``. It needs no remote code.

Why this module exists:

- The checkpoint ships remote code (``modeling_qwen3_bidirectional.py``). Onyx
  never runs remote code: ``trust_remote_code`` stays False for every model.
  That code also fails on transformers 5.14.1 (``create_causal_mask()`` gets an
  unexpected keyword argument ``input_embeds``).
- Without remote code, a plain ``SentenceTransformer`` load gives wrong vectors
  and no error. transformers loads the native ``Qwen3Model``, which is causal,
  and drops the checkpoint's bias-free ``linear.weight`` (1024 -> 2048) as an
  unexpected key. The vectors have 1024 dims, but the Pooling config reports
  2048.

The fix below reproduces the remote model with native code only:

1. Set ``config.is_causal = False`` after the load. The Qwen3 forward reads it
   on every call, which gives a bidirectional attention mask, also for padded
   batches. ``config_kwargs={"is_causal": False}`` does not work, because
   ``Qwen3Config`` has no such attribute and transformers ignores the kwarg.
2. Add the checkpoint's ``linear.weight`` as a bias-free ``Dense`` layer after
   mean pooling. The remote code applies it to each token before pooling. Mean
   pooling is linear and the layer has no bias or activation, so the two orders
   give the same vector.

Checked on real weights against an independent re-implementation of the remote
model: 1 - cosine < 2e-7, and a padded batch equals single inputs.
"""

from typing import TYPE_CHECKING

import torch

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

# The checkpoint file that holds the projection, and the tensor name in it.
VOYAGE_NANO_PROJECTION_FILE = "model.safetensors"
_PROJECTION_WEIGHT_KEY = "linear.weight"
# Transformer -> Pooling -> Normalize, from the checkpoint's modules.json.
_EXPECTED_MODULE_COUNT = 3


class VoyageNanoLoadError(RuntimeError):
    """The loaded checkpoint does not have the expected voyage-4-nano layout."""


def read_projection_weight(safetensors_path: str) -> torch.Tensor:
    """Read the bias-free projection weight, shape [out_dim, hidden_dim]."""
    from safetensors import safe_open

    with safe_open(safetensors_path, framework="pt") as checkpoint:
        if _PROJECTION_WEIGHT_KEY not in checkpoint.keys():
            raise VoyageNanoLoadError(
                f"{safetensors_path} has no '{_PROJECTION_WEIGHT_KEY}' tensor."
            )
        weight = checkpoint.get_tensor(_PROJECTION_WEIGHT_KEY)
    if weight.dim() != 2:
        raise VoyageNanoLoadError(
            f"'{_PROJECTION_WEIGHT_KEY}' must be 2-D, got shape {tuple(weight.shape)}."
        )
    return weight


def add_bidirectional_projection(
    model: "SentenceTransformer", projection_weight: torch.Tensor
) -> "SentenceTransformer":
    """Return voyage-4-nano with bidirectional attention and the 2048-dim projection.

    ``model`` is the plain native load (Transformer -> Pooling -> Normalize).
    """
    from sentence_transformers import SentenceTransformer
    from sentence_transformers.base.modules import Transformer
    from sentence_transformers.sentence_transformer.modules import Dense

    if len(model) != _EXPECTED_MODULE_COUNT:
        raise VoyageNanoLoadError(
            f"Expected {_EXPECTED_MODULE_COUNT} modules (Transformer, Pooling, "
            f"Normalize), got {len(model)}."
        )
    transformer, pooling, normalize = model[0], model[1], model[2]
    if not isinstance(transformer, Transformer):
        raise VoyageNanoLoadError(
            f"Expected a Transformer as the first module, got {type(transformer).__name__}."
        )

    transformer.auto_model.config.is_causal = False

    projection = Dense(
        in_features=projection_weight.shape[1],
        out_features=projection_weight.shape[0],
        bias=False,
        activation_function=None,  # identity
        init_weight=projection_weight,
    )
    return SentenceTransformer(modules=[transformer, pooling, projection, normalize])
