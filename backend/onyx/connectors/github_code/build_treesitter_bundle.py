# File: backend/onyx/connectors/github_code/build_treesitter_bundle.py

import os
from tree_sitter import Language

# 1. Define where to output the .so and which grammar repos to include.
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GRAMMAR_DIR = os.path.join(BASE_DIR, "vendor", "tree-sitter-grammars")
OUTPUT_PATH = os.path.join("/usr/local/lib", "my-languages.so")  # install location inside Docker

# 2. List the paths to each local grammar directory.
LANGUAGE_REPOS = [
    os.path.join(GRAMMAR_DIR, "tree-sitter-javascript"),
    os.path.join(GRAMMAR_DIR, "tree-sitter-typescript", "typescript"),  # note: TS grammar is nested under “typescript/”
    os.path.join(GRAMMAR_DIR, "tree-sitter-ruby"),
    os.path.join(GRAMMAR_DIR, "tree-sitter-c-sharp"),
]

def build_shared_library():
    """
    Invokes Tree-sitter’s build process to compile all grammars into a single .so.
    """
    # Make sure output directory exists
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    print(f"Building Tree-sitter bundle at: {OUTPUT_PATH}")
    Language.build_library(
        # Destination of the compiled .so
        OUTPUT_PATH,
        # List of grammar source directories
        LANGUAGE_REPOS
    )
    print("Done building Tree-sitter shared library.")

if __name__ == "__main__":
    build_shared_library()
