from evaluation.rerank_eval import collapse_chunk_results_to_documents


def test_collapse_chunk_results_prefers_best_rerank_score_and_trims_top_k():
    chunk_results = [
        {
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "score": 0.92,
            "rerank_score": 0.20,
            "metadata": {"file_name": "doc-1.pdf"},
        },
        {
            "chunk_id": "chunk-2",
            "document_id": "doc-1",
            "score": 0.81,
            "rerank_score": 0.95,
            "metadata": {"file_name": "doc-1.pdf"},
        },
        {
            "chunk_id": "chunk-3",
            "document_id": "doc-2",
            "score": 0.85,
            "rerank_score": 0.70,
            "metadata": {"file_name": "doc-2.pdf"},
        },
        {
            "chunk_id": "chunk-4",
            "document_id": "doc-3",
            "score": 0.73,
            "rerank_score": 0.80,
            "metadata": {"file_name": "doc-3.pdf"},
        },
    ]

    ranked_documents = collapse_chunk_results_to_documents(
        chunk_results,
        score_key="rerank_score",
        top_k=2,
    )

    assert [item["document_id"] for item in ranked_documents] == ["doc-1", "doc-3"]
    assert ranked_documents[0]["chunk_id"] == "chunk-2"
    assert ranked_documents[0]["selected_score"] == 0.95
