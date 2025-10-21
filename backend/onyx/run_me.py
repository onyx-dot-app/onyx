# run_me.py
from types import SimpleNamespace
from onyx.chat.stream_processing.citation_processing import CitationProcessor

# Build the long test string (your example)
stream_text = (
    "Eco-innovation refers to advancements that reduce environmental impacts, enhance resilience to environmental pressures, "
    "or improve the efficient use of natural resources. It encompasses performance across five dimensions: inputs, activities, "
    "outputs, resource efficiency outcomes, and socio-economic outcomes [1,2]"
    "out[3,4]"
    # "17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44]."
    # "outputs, resource efficiency outcomes, and socio-economic outcomes [[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], [11, 12, 13, 14, 15, 16, "
    # "17, 18, 19, 20], [21, 22, 23, 24, 25, 26, 27, 28, 29, 30], [31, 32, 33, 34, 35, 36, 37, 38, 39, 40], [41, 42, 43, 44]]."
)

# Minimal context: 44 docs so citations [1..44] are "valid"
num_docs = 44
context_docs = [
    SimpleNamespace(document_id=f"doc-{i}", link=f"https://example.com/{i}") for i in range(1, num_docs + 1)
]

# Provide the order mappings expected by CitationProcessor via .order_mapping
# Map final order: document_id -> displayed_number (1..44)
display_map = {f"doc-{i}": i for i in range(1, num_docs + 1)}
final_map = display_map.copy()

final_doc_id_to_rank_map = SimpleNamespace(order_mapping=final_map)
display_doc_id_to_rank_map = SimpleNamespace(order_mapping=display_map)

processor = CitationProcessor(
    context_docs=context_docs,
    final_doc_id_to_rank_map=final_doc_id_to_rank_map,
    display_doc_id_to_rank_map=display_doc_id_to_rank_map,
    stop_stream=None,  # disable stop token for testing
)

def stream_in_chunks(text: str, chunk_size: int = 5):
    # Chunk the text to simulate token streaming
    for i in range(0, len(text), chunk_size):
        yield text[i : i + chunk_size]
    # Signal end-of-stream
    yield None

# Collect outputs
answer = []
citations = []

for tok in stream_in_chunks(stream_text, chunk_size=5):  # try 1 for char-by-char
    for item in processor.process_token(tok):
        # OnyxAnswerPiece or CitationInfo
        if hasattr(item, "answer_piece"):
            answer.append(item.answer_piece)
        else:
            citations.append(item)

print("ANSWER:")
print("".join(answer))

print("\nCITATIONS EMITTED (display numbers):")
# for c in citations:
#     # CitationInfo(citation_num, document_id)
#     print(c.citation_num, c.document_id)