import copy
import json
import unittest

from attribution import POLICY_VERSION, attribute_answer


class AttributionTests(unittest.TestCase):
    def fixture(self, question="What is the name of my cat?", answer="Luna", sources=None, citations=None):
        sources = sources or [("s_cat", "user", "My cat's name is Luna.")]
        sessions = [{"session_id": sid, "date": "2023/05/24 (Wed) 17:25",
                     "turns": [{"role": role, "content": text}]} for sid, role, text in sources]
        history = {"history_id": "h_test", "sessions": sessions}
        q = {"question_id": "q_test", "history_id": "h_test", "question": question,
             "question_date": "2023/05/30 (Tue) 12:18"}
        evidence = [{"id": s["session_id"], "date": s["date"],
                     "text": f"{s['turns'][0]['role']}: {s['turns'][0]['content']}"} for s in sessions]
        result = {"status": "answered", "question_id": "q_test", "answer": answer,
                  "reply": f"Explanation [E1].\n# FINAL ANSWER [ref:56451236]: {answer}",
                  "abstained": False, "citations": citations or [], "unknown_citations": []}
        return q, history, evidence, result

    def assert_spans(self, attributed, history, evidence):
        sessions = {s["session_id"]: s for s in history["sessions"]}
        for support in attributed["supports"]:
            text = evidence[support["evidence_index"]]["text"]
            self.assertEqual(text[support["start"]:support["end"]], support["span"])
            self.assertEqual(evidence[support["evidence_index"]]["id"], support["source_id"])
            self.assertTrue(any(t["role"] == support["role"] and support["span"] in t["content"]
                                for t in sessions[support["source_id"]]["turns"]))

    def test_historical_luna_exact_span_and_raw_result_preserved(self):
        source = ("By the way, my cat's name is Luna, and she's been such a sweetie throughout "
                  "all the changes we've been making to her environment. I'm just glad I can "
                  "provide her with a happy and healthy home.")
        args = self.fixture(sources=[("s_8a377a1e6a80", "user", source)])
        before = copy.deepcopy(args)
        got = attribute_answer(*args)
        self.assertEqual(args, before)
        self.assertEqual(got["policy_version"], POLICY_VERSION)
        self.assertEqual(got["reactor_citations"], [])
        self.assertEqual(got["fallback_citations"], ["s_8a377a1e6a80"])
        self.assertEqual(got["unresolved_claims"], [])
        self.assertEqual(got["supports"][0]["span"], "my cat's name is Luna")
        self.assertEqual(got["supports"][0]["role"], "user")
        self.assert_spans(got, args[1], args[2])
        json.dumps(got)

    def test_supplied_official_citations_and_records_remain_separate(self):
        args = self.fixture(answer="Luna [E1]", citations=[{"label": "E1", "id": "s_cat"}])
        got = attribute_answer(*args)
        self.assertEqual(got["reactor_citations"], ["s_cat"])
        self.assertEqual(got["reactor_citation_records"], args[3]["citations"])
        self.assertEqual(got["fallback_citations"], [])
        self.assertEqual(got["final_citations"], ["s_cat"])
        got["reactor_citation_records"][0]["id"] = "changed"
        self.assertEqual(args[3]["citations"][0]["id"], "s_cat")

    def test_two_facts_require_union_and_complete_missing_supplied_citation(self):
        args = self.fixture(question="What are the names of my cat and my dog?",
                            answer="cat: Luna; dog: Rex [E1]",
                            sources=[("s_cat", "user", "My cat's name is Luna."),
                                     ("s_dog", "user", "My dog's name is Rex.")],
                            citations=[{"label": "E1", "id": "s_cat"}])
        got = attribute_answer(*args)
        self.assertEqual(got["reactor_citations"], ["s_cat"])
        self.assertEqual(got["fallback_citations"], ["s_dog"])
        self.assertEqual(got["final_citations"], ["s_cat", "s_dog"])
        self.assertEqual(len(got["supports"]), 2)
        self.assert_spans(got, args[1], args[2])

    def test_multiple_facts_same_session_deduplicate(self):
        args = self.fixture(question="What are the names of my cat and my dog?", answer="cat: Luna; dog: Rex",
                            sources=[("s_pets", "user", "My cat's name is Luna. My dog's name is Rex.")])
        got = attribute_answer(*args)
        self.assertEqual(got["fallback_citations"], ["s_pets"])
        self.assertEqual(len(got["supports"]), 2)
        self.assert_spans(got, args[1], args[2])

    def test_multi_source_explicit_item_union(self):
        args = self.fixture(question="Which courses have I completed?", answer="Python Basics and Data Analysis",
                            sources=[("s_one", "user", "I completed the course Python Basics."),
                                     ("s_two", "user", "I completed the course Data Analysis.")])
        got = attribute_answer(*args)
        self.assertEqual(got["fallback_citations"], ["s_one", "s_two"])
        self.assertEqual(got["unresolved_claims"], [])
        self.assert_spans(got, args[1], args[2])

    def test_partial_fact_coverage_does_not_add_fallback(self):
        args = self.fixture(question="What are the names of my cat and my dog?", answer="cat: Luna; dog: Rex")
        got = attribute_answer(*args)
        self.assertEqual(got["fallback_citations"], [])
        self.assertEqual(len(got["supports"]), 1)
        self.assertEqual(got["unresolved_claims"][0]["claim"], "dog: Rex")

    def test_assistant_recommendation_requires_role_and_exact_target(self):
        args = self.fixture(question="What did the assistant recommend for my dry skin?",
                            answer="a fragrance-free moisturizer",
                            sources=[("s_advice", "assistant", "For your dry skin, I recommend a fragrance-free moisturizer.")])
        got = attribute_answer(*args)
        self.assertEqual(got["fallback_citations"], ["s_advice"])
        self.assertEqual(got["supports"][0]["role"], "assistant")
        self.assert_spans(got, args[1], args[2])
        for role, target in [("user", "dry"), ("assistant", "oily")]:
            bad = self.fixture(question=args[0]["question"], answer=args[3]["answer"],
                               sources=[("s_advice", role, f"For your {target} skin, I recommend a fragrance-free moisturizer.")])
            self.assertEqual(attribute_answer(*bad)["fallback_citations"], [])

    def test_wrong_entity_owner_or_role_never_uses_answer_token_alone(self):
        for role, source in [("user", "My hamster's name is Luna."),
                             ("user", "My sister's cat's name is Luna."),
                             ("assistant", "My cat's name is Luna."),
                             ("user", "Luna is a nice name for a cat.")]:
            with self.subTest(role=role, source=source):
                got = attribute_answer(*self.fixture(sources=[("s_wrong", role, source)]))
                self.assertEqual(got["fallback_citations"], [])
                self.assertTrue(got["unresolved_claims"])

    def test_negative_conditional_quoted_and_conflicting_assertions(self):
        sources = ["My cat's name is not Luna.", "Maybe my cat's name is Luna.",
                   "If my cat's name is Luna, I will be surprised.",
                   'The example says "my cat\'s name is Luna".',
                   "My cat's name is Luna, not Stella.",
                   "My cat's name is Luna, but we changed it to Stella.",
                   "My cat's name is Luna, she may be renamed Stella.",
                   "My cat's name is Luna, says Alice.",
                   "My cat's name is Luna. Just kidding.",
                   "My cat's name is Luna. My cat's name is Stella."]
        for source in sources:
            with self.subTest(source=source):
                self.assertEqual(attribute_answer(*self.fixture(sources=[("s_bad", "user", source)]))["fallback_citations"], [])

    def test_fabricated_excerpt_wrong_date_foreign_session_and_role_spoof(self):
        for mutation in ("fabrication", "foreign", "date", "role_spoof", "future"):
            args = self.fixture()
            if mutation == "fabrication":
                args[1]["sessions"][0]["turns"][0]["content"] = "My cat's name is Stella."
            elif mutation == "foreign":
                args[2][0]["id"] = "s_other_user"
            elif mutation == "date":
                args[2][0]["date"] = "2024-01-01"
            elif mutation == "role_spoof":
                args[1]["sessions"][0]["turns"][0]["role"] = "assistant"
            else:
                args[0]["question_date"] = "2023-05-01"
            with self.subTest(mutation=mutation):
                self.assertEqual(attribute_answer(*args)["fallback_citations"], [])

    def test_cropped_original_report_quote_conditional_and_negation_are_rejected(self):
        for original in ["Alice said: My cat's name is Luna.",
                         'Alice said: "My cat\'s name is Luna."',
                         "If My cat's name is Luna, I would be surprised.",
                         "My cat's name is Luna, not really though.",
                         "My cat's name is Luna. Just kidding.",
                         "My cat's name is Luna. My cat's name is Stella."]:
            args = self.fixture()
            args[1]["sessions"][0]["turns"][0]["content"] = original
            with self.subTest(original=original):
                got = attribute_answer(*args)
                self.assertEqual(got["fallback_citations"], [])
                self.assertEqual(got["supports"], [])

    def test_fabricated_metadata_is_not_a_supplied_final_citation(self):
        args = self.fixture(citations=[{"label": "E1", "id": "s_cat"}])
        got = attribute_answer(*args)
        self.assertEqual(got["reactor_citation_records"], args[3]["citations"])
        self.assertEqual(got["final_citations"], [])
        self.assertEqual(got["fallback_citations"], [])
        self.assertIn("citation_metadata_mismatch", [x["reason"] for x in got["unresolved_claims"]])

    def test_actual_final_unknown_and_missing_metadata_are_rejected(self):
        for answer in ["Luna [E2]", "Luna [E1]"]:
            got = attribute_answer(*self.fixture(answer=answer))
            self.assertEqual(got["fallback_citations"], [])
            self.assertEqual(got["final_citations"], [])
            self.assertIn("citation_metadata_mismatch", [x["reason"] for x in got["unresolved_claims"]])

    def test_unsupported_synthesis_arithmetic_boolean_and_hedging(self):
        for question, answer in [("How many courses have I completed in total?", "5"),
                                 ("Is my cat named Luna?", "Yes"),
                                 ("When did I adopt my cat?", "May 2023"),
                                 ("What is the name of my cat?", "Luna or Stella"),
                                 ("What is the name of my cat?", "Luna because she is sweet")]:
            with self.subTest(question=question, answer=answer):
                got = attribute_answer(*self.fixture(question=question, answer=answer))
                self.assertEqual(got["fallback_citations"], [])
                self.assertTrue(got["unresolved_claims"])

    def test_failed_or_abstained_reactor_is_never_changed_to_answer(self):
        for status, answer, abstained in [("timeout", "", False), ("answered", "INSUFFICIENT_EVIDENCE", True)]:
            args = self.fixture(answer=answer)
            args[3].update(status=status, abstained=abstained)
            before = copy.deepcopy(args)
            self.assertEqual(attribute_answer(*args)["fallback_citations"], [])
            self.assertEqual(args, before)

    def test_abstention_with_final_label_preserves_raw_but_finalizes_no_citations(self):
        for abstained in (True, False):
            args = self.fixture(answer="INSUFFICIENT_EVIDENCE [E1]",
                                citations=[{"label": "E1", "id": "s_cat"}])
            args[3]["abstained"] = abstained
            before = copy.deepcopy(args)
            got = attribute_answer(*args)
            self.assertEqual(got["reactor_citations"], ["s_cat"])
            self.assertEqual(got["reactor_citation_records"], args[3]["citations"])
            self.assertEqual(got["final_citations"], [])
            self.assertEqual(got["fallback_citations"], [])
            self.assertEqual(got["supports"], [])
            self.assertEqual(args, before)

    def test_invalid_supplied_citation_is_retained_but_not_finalized(self):
        for record in [{"label": "E2", "id": "s_cat"}, {"label": "E1", "id": "s_foreign"}]:
            args = self.fixture(citations=[record])
            got = attribute_answer(*args)
            self.assertEqual(got["reactor_citation_records"], [record])
            self.assertEqual(got["reactor_citations"], [record["id"]])
            self.assertEqual(got["fallback_citations"], [])
            self.assertEqual(got["final_citations"], [])
            self.assertIn("invalid_reactor_citation", [x["reason"] for x in got["unresolved_claims"]])

    def test_question_or_history_mismatch_prevents_fallback(self):
        args = self.fixture()
        args[0]["history_id"] = "h_foreign"
        self.assertEqual(attribute_answer(*args)["fallback_citations"], [])
        args = self.fixture()
        args[3]["question_id"] = "q_foreign"
        self.assertEqual(attribute_answer(*args)["fallback_citations"], [])


if __name__ == "__main__":
    unittest.main()
