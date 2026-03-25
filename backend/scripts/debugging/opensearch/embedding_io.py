from shared_configs.model_server_models import Embedding


def load_query_embedding_from_file(file_path: str) -> Embedding:
    """Returns an embedding vector read from a file.

    The file should be formatted as follows:
    - The first line should contain an integer representing the embedding
      dimension.
    - Every subsequent line should contain a float value representing a
      component of the embedding vector.
    - The size and embedding content should all be delimited by a newline.

    Args:
        file_path: Path to the file containing the embedding vector.

    Returns:
        Embedding: The embedding vector.
    """
    with open(file_path, "r") as f:
        dimension = int(f.readline().strip())
        embedding = [float(line.strip()) for line in f.readlines()]
        assert len(embedding) == dimension, "Embedding dimension mismatch."
        return embedding


def save_query_embedding_to_file(embedding: Embedding, file_path: str) -> None:
    """Saves an embedding vector to a file.

    The file will be formatted as follows:
    - The first line will contain the embedding dimension.
    - Every subsequent line will contain a float value representing a
      component of the embedding vector.
    - The size and embedding content will all be delimited by a newline.

    Args:
        embedding: The embedding vector to save.
        file_path: Path to the file to save the embedding vector to.
    """
    with open(file_path, "w") as f:
        f.write(f"{len(embedding)}\n")
        for component in embedding:
            f.write(f"{component}\n")
