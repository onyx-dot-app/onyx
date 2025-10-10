"""
Script to list all supported embedding models from fastembed.

Shows both dense (TextEmbedding) and sparse (SparseTextEmbedding) models.
"""

from fastembed import SparseTextEmbedding
from fastembed import TextEmbedding


def main():
    print("=" * 80)
    print("DENSE EMBEDDING MODELS (TextEmbedding)")
    print("=" * 80)
    print()

    dense_models = TextEmbedding.list_supported_models()
    print(f"Total models: {len(dense_models)}\n")

    for idx, model in enumerate(dense_models, start=1):
        print(f"{idx}. {model['model']}")
        print(f"   Dimension: {model['dim']}")
        print(f"   Description: {model.get('description', 'N/A')}")
        print(f"   Size: {model.get('size_in_GB', 'N/A')} GB")
        print()

    print("=" * 80)
    print("SPARSE EMBEDDING MODELS (SparseTextEmbedding)")
    print("=" * 80)
    print()

    sparse_models = SparseTextEmbedding.list_supported_models()
    print(f"Total models: {len(sparse_models)}\n")

    for idx, model in enumerate(sparse_models, start=1):
        print(f"{idx}. {model['model']}")
        print(f"   Description: {model.get('description', 'N/A')}")
        print(f"   Size: {model.get('size_in_GB', 'N/A')} GB")
        print()


if __name__ == "__main__":
    main()
