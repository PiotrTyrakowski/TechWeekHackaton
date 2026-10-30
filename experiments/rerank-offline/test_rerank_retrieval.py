import retrieval_rerank


def test_rank_prefers_full_query_coverage_and_respects_budget():
    history = {"sessions": [
        {"session_id": "s1", "date": "d1", "turns": [{"role": "user", "content": "I like tea and coffee"}]},
        {"session_id": "s2", "date": "d2", "turns": [{"role": "user", "content": "Coffee is nice"}]},
    ]}
    got = retrieval_rerank.retrieve({"question": "tea coffee"}, history, k=2, budget=100)
    assert got[0]["id"] == "s1"
    assert sum(len(row["text"]) for row in got) <= 100


def test_deduplicates_sessions_and_validates_method():
    history = {"sessions": [{"session_id": "s1", "date": "d", "turns": [
        {"role": "user", "content": "likes tea"}, {"role": "assistant", "content": "tea is good"}
    ]}]}
    got = retrieval_rerank.retrieve({"question": "tea"}, history, k=4)
    assert len(got) == 1
    try:
        retrieval_rerank.retrieve({"question": "tea"}, history, method="unknown")
    except ValueError:
        pass
    else:
        raise AssertionError("expected unsupported method to fail")
