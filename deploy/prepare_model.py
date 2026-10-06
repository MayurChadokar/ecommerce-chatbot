"""Download the production embedding cache once, then verify offline loading."""

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "huggingface"))
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    from sentence_transformers import SentenceTransformer
    from product_index import EMBEDDING_MODEL, EMBEDDING_DIMENSION

    model = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
    if model.get_sentence_embedding_dimension() != EMBEDDING_DIMENSION:
        raise RuntimeError("Embedding dimension does not match the product index")
    del model
    cached = SentenceTransformer(EMBEDDING_MODEL, device="cpu", local_files_only=True)
    if cached.get_sentence_embedding_dimension() != EMBEDDING_DIMENSION:
        raise RuntimeError("Cached embedding model has the wrong dimension")
    print("Embedding model downloaded and offline loading verified.")


if __name__ == "__main__":
    main()
