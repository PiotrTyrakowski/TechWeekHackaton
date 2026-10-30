import io
import json
from pathlib import Path
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from official.reactor import client as official
from official.reactor import predictions
import reactor_client


class ReactorClientTests(unittest.TestCase):
    evidence = [{"id": "s_cat", "date": "2023/05/20 (Sat) 02:21", "text": "user: My cat's name is Luna."}]

    def test_explanation_citation_is_not_a_final_answer_citation(self):
        reply = "Your cat's name is Luna [E1].\n\n# FINAL ANSWER [ref:1234abcd]: Luna"
        answer = official.final_answers(reply)["1234abcd"]
        self.assertEqual(answer, "Luna")
        self.assertEqual(official.citations(answer, self.evidence), ([], []))
        # Only Reactor putting the citation on its final line fixes evidence F1.
        cited_reply = "# FINAL ANSWER [ref:1234abcd]: Luna [E1]"
        cited_answer = official.final_answers(cited_reply)["1234abcd"]
        self.assertEqual(official.citations(cited_answer, self.evidence),
                         ([{"label": "E1", "id": "s_cat"}], []))

    def test_stored_uncited_trace_is_not_repaired(self):
        path = Path(__file__).resolve().parents[1] / "reports/live-smoke-20261030T2135/results.jsonl"
        with path.open() as stream:
            result = json.loads(next(stream))
        answer = official.final_answers(result["reply"])[result["ref"]]
        self.assertIn("[E1]", result["reply"])
        self.assertEqual(answer, result["answer"])
        self.assertEqual(official.citations(answer, self.evidence), ([], []))
        converted, skipped, notes = predictions.convert([result], {"agent"}, {"s_cat"})
        self.assertEqual((converted[0]["answer"], converted[0]["citations"]), ("Luna", []))
        self.assertEqual((skipped, notes), ([], []))

    def test_prompt_requires_labels_on_final_line_and_preserves_dates(self):
        prompt = reactor_client.build_message("What is my cat's name?", self.evidence,
                                             "1234abcd", "2023-05-30 12:18")
        self.assertIn("final answer line itself MUST include", prompt)
        self.assertIn("A citation anywhere before the final answer line does not count", prompt)
        self.assertIn("Use only labels supplied in this question: [E1]", prompt)
        self.assertIn("date: 2023/05/20 (Sat) 02:21", prompt)
        self.assertIn("Question date: 2023-05-30 (Tue) 12:18", prompt)
        self.assertIn("INSUFFICIENT_EVIDENCE", prompt)

    def test_final_answer_is_a_segment_not_just_one_physical_line(self):
        # The participant guide says "line", but the source parser continues
        # through the end of the reply or the next final-answer marker.
        reply = ("# FINAL ANSWER [ref:1234abcd]: Luna\n[E1]\n"
                 "# FINAL ANSWER [ref:5678abcd]: A late different answer [E9]")
        answer = official.final_answers(reply)["1234abcd"]
        self.assertEqual(answer, "Luna\n[E1]")
        self.assertEqual(official.citations(answer, self.evidence),
                         ([{"label": "E1", "id": "s_cat"}], []))
        self.assertEqual(predictions.strip_labels(answer), "Luna")

    def test_reused_labels_map_only_to_current_question_evidence(self):
        earlier = [{"id": "s_dog", "text": "user: My dog is called Rover."}]
        answer = "Luna [E1]"
        self.assertEqual(official.citations(answer, earlier)[0][0]["id"], "s_dog")
        self.assertEqual(official.citations(answer, self.evidence)[0][0]["id"], "s_cat")
        prompt = reactor_client.build_message("What is my cat's name?", self.evidence, "1234abcd")
        self.assertIn("For ref:1234abcd, evidence labels are local to THIS question", prompt)
        self.assertIn("Do not reuse citations from prior replies", prompt)

    def test_multiple_passages_deduplicate_sessions_and_reject_unknown_labels(self):
        evidence = [
            {"id": "s_a", "text": "user: First hike: 3 miles."},
            {"id": "s_b", "text": "user: Second hike: 4 miles."},
            {"id": "s_a", "text": "assistant: You walked 3 miles."},
        ]
        answer = "7 miles [E1, E2] [E3] [E99]."
        cited, unknown = official.citations(answer, evidence)
        self.assertEqual(unknown, ["E99"])
        result = {"question_id": "q_hikes", "status": "answered", "answer": answer,
                  "abstained": False, "citations": cited, "unknown_citations": unknown}
        converted, skipped, notes = predictions.convert([result], {"agent"}, {"s_a", "s_b"})
        self.assertEqual(converted, [{"question_id": "q_hikes", "abstain": False,
                                    "answer": "7 miles.", "citations": ["s_a", "s_b"]}])
        self.assertEqual(skipped, [])
        self.assertTrue(any("E99 wasn't among the passages sent" in note for note in notes))
        # The converter can drop unknown labels, but runtime must reject them;
        # this test documents the official adapter rather than blessing repair.

    def test_memory_without_current_evidence_has_no_mappable_citations(self):
        prompt = reactor_client.build_message("What is my cat's name?", [], "1234abcd")
        self.assertIn("No evidence labels were supplied", prompt)
        self.assertNotIn("<supporting current evidence labels>", prompt)
        self.assertEqual(official.citations("Luna [E1]", []), ([], ["E1"]))
        self.assertEqual(official.citations("Luna, from session s_cat", []), ([], []))

    def test_actual_abstention_is_distinct_from_a_failed_request(self):
        converted, skipped, _ = predictions.convert([
            {"question_id": "q_abs", "status": "answered", "answer": "INSUFFICIENT_EVIDENCE",
             "abstained": True, "citations": []},
            {"question_id": "q_timeout", "status": "timeout"},
        ], {"agent"}, {"s_cat"})
        self.assertEqual(converted, [{"question_id": "q_abs", "abstain": True,
                                    "answer": "", "citations": []}])
        self.assertEqual(len(skipped), 1)
        self.assertIn("q_timeout", skipped[0])

    def test_simulated_frames_keep_current_final_citation_through_official_conversion(self):
        # No remote service: exercise the real async parser and official result
        # adapter with an interim citation, stale final, and current final.
        class FakeSocket:
            close_code = 1000
            close_reason = ""

            async def send(self, raw):
                self.text = json.loads(raw)["text"]

            async def __aiter__(self):
                yield json.dumps({"type": "ack", "cycle": 2, "text": self.text})
                yield json.dumps({"type": "reply", "cycle": 3, "text": "Checking Luna [E1]."})
                yield json.dumps({"type": "reply", "cycle": 4,
                                  "text": "# FINAL ANSWER [ref:5678abcd]: Rover [E1]"})
                yield json.dumps({"type": "reply", "cycle": 5,
                                  "text": "# FINAL ANSWER [ref:1234abcd]: Luna [E1]"})

        @asynccontextmanager
        async def connect(*args, **kwargs):
            yield FakeSocket()

        with patch.object(official, "environment_problem", return_value=None), \
             patch.dict(official.os.environ, {"REACTOR_ACCESS_KEY": "test-key"}), \
             patch.object(reactor_client, "_connect", connect), \
             patch.object(official.secrets, "token_hex", return_value="1234abcd"), \
             patch.object(official, "_read", return_value=json.dumps(self.evidence)), \
             patch("sys.stdout", new_callable=io.StringIO) as stdout, \
             patch("sys.stderr", new_callable=io.StringIO):
            code = reactor_client.main(["--base-url", "https://example.test", "--agent-id", "agt_test",
                                        "--history", "hist", "--question", "What is my cat's name?",
                                        "--question-id", "q_cat", "--evidence", "unused.json"])
        self.assertEqual(code, 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["answer"], "Luna [E1]")
        self.assertEqual(result["citations"], [{"label": "E1", "id": "s_cat"}])
        self.assertEqual(result["late_replies"][0]["answer"], "Rover [E1]")
        self.assertFalse(result["uncited"])
        converted, skipped, notes = predictions.convert([result], {"agent"}, {"s_cat"})
        self.assertEqual(converted, [{"question_id": "q_cat", "abstain": False,
                                    "answer": "Luna", "citations": ["s_cat"]}])
        self.assertEqual((skipped, notes), ([], []))

    def test_main_wraps_prompt_only_and_restores_official_function(self):
        original = official.build_message
        def fake_main(argv):
            self.assertIs(official.build_message, reactor_client.build_message)
            self.assertEqual(argv, ["--help"])
            return 0
        with patch.object(official, "main", side_effect=fake_main):
            self.assertEqual(reactor_client.main(["--help"]), 0)
        self.assertIs(official.build_message, original)

    def test_official_prompt_mode_is_exact_and_scoped(self):
        expected = official.build_message("Cat?", self.evidence, "1234abcd")
        self.assertEqual(reactor_client.build_message("Cat?", self.evidence, "1234abcd",
                                                     citation_mode="official"), expected)
        original = official.build_message
        def fake_main(argv):
            self.assertEqual(argv, ["--help"])
            self.assertEqual(official.build_message("Cat?", self.evidence, "1234abcd"), expected)
            return 0
        with patch.object(official, "main", side_effect=fake_main):
            self.assertEqual(reactor_client.main(["--citation-mode", "official", "--help"]), 0)
        self.assertIs(official.build_message, original)

    def test_wrapper_defaults_and_safe_backoff_are_scoped(self):
        first, maximum = official._RETRY_FIRST, official._RETRY_MAX
        def fake_main(argv):
            self.assertEqual(argv[-2:], ["--timeout", "600"])
            self.assertEqual((official._RETRY_FIRST, official._RETRY_MAX), (5.0, 10.0))
            return 0
        with patch.object(official, "main", side_effect=fake_main):
            self.assertEqual(reactor_client.main(["--question", "Cat?"]), 0)
        self.assertEqual((official._RETRY_FIRST, official._RETRY_MAX), (first, maximum))

    def test_refused_forwarding_metadata_is_preserved_without_changing_transport(self):
        refused = official.Refused("previous_pending", "wait", [], [], {"forwarded": False})
        with patch.object(official, "environment_problem", return_value=None), \
             patch.dict(official.os.environ, {"REACTOR_ACCESS_KEY": "test-key"}), \
             patch.object(official, "ask_retrying", side_effect=refused), \
             patch("sys.stdout", new_callable=io.StringIO) as stdout, \
             patch("sys.stderr", new_callable=io.StringIO):
            code = reactor_client.main(["--base-url", "https://example.test", "--agent-id", "test",
                                        "--history", "own-history", "--question", "Cat?"])
        self.assertEqual(code, 4)
        result = json.loads(stdout.getvalue())
        self.assertIs(result["forwarded"], False)
        self.assertEqual(result["outcome_kind"], "pending")
        self.assertEqual(result["history_id"], "own-history")

    def test_official_previous_pending_backoff_only_retries_explicitly_unforwarded(self):
        for forwarded, expected_calls in ((False, 2), (True, 1), (None, 1)):
            with self.subTest(forwarded=forwarded):
                refused = official.Refused("previous_pending", "wait", [], [], {"forwarded": forwarded})
                response = {"answer": "Luna [E1]", "late_replies": []}
                ask = AsyncMock(side_effect=[refused, response])
                with patch.object(official, "ask", ask), patch.object(official.time, "sleep") as sleep:
                    if forwarded is False:
                        result, retries = official.ask_retrying("https://example.test", "test", "key", "Cat?",
                                                               timeout=300, ref="1234abcd", history="own-history")
                        self.assertEqual((result["answer"], retries), ("Luna [E1]", 1))
                        sleep.assert_called_once_with(1.0)
                    else:
                        with self.assertRaises(official.Refused):
                            official.ask_retrying("https://example.test", "test", "key", "Cat?", timeout=300)
                        sleep.assert_not_called()
                self.assertEqual(ask.await_count, expected_calls)

    def test_history_post_response_is_passed_through_without_id_replacement(self):
        response = {"agent_id": "agt_test", "history_id": "from-server", "running": True}
        with patch.object(official.urllib.request, "urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode()
            result = official.new_history("https://example.test", "agt_test", "test-key", timeout=1)
        self.assertEqual(result, response)
        req = urlopen.call_args.args[0]
        self.assertEqual(req.method, "POST")
        self.assertEqual(req.full_url, "https://example.test/agents/agt_test/history")

    def test_closed_reason_remains_in_official_stderr(self):
        # Keep the organizer's output behavior; runtime captures this stderr.
        with patch.object(official, "environment_problem", return_value=None), \
             patch.dict(official.os.environ, {"REACTOR_ACCESS_KEY": "test-key"}), \
             patch.object(official, "ask_retrying", side_effect=official.Closed("closed by server (1011): restart", [], [])), \
             patch("sys.stdout", new_callable=io.StringIO) as stdout, \
             patch("sys.stderr", new_callable=io.StringIO) as stderr:
            code = reactor_client.main(["--base-url", "https://example.test", "--agent-id", "agt_test",
                                        "--history", "hist", "--question", "What?", "--question-id", "q1"])
        self.assertEqual(code, 5)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "closed")
        self.assertIn("1011", stderr.getvalue())
        self.assertIn("restart", stderr.getvalue())

    def test_clean_close_diagnostics_preserve_metadata_without_message_content(self):
        class FakeSocket:
            close_code = 1000
            close_reason = "history reset test-key"

            async def send(self, text):
                self.text = json.loads(text)["text"]

            async def __aiter__(self):
                yield json.dumps({"type": "ack", "cycle": 4, "text": self.text})
                yield json.dumps({"type": "error", "code": "history_changed", "text": "private-chat-content"})

        @asynccontextmanager
        async def connect(*args, **kwargs):
            yield FakeSocket()

        with patch.object(official, "environment_problem", return_value=None), \
             patch.dict(official.os.environ, {"REACTOR_ACCESS_KEY": "test-key"}), \
             patch.object(reactor_client, "_connect", connect), \
             patch("sys.stdout", new_callable=io.StringIO) as stdout, \
             patch("sys.stderr", new_callable=io.StringIO) as stderr:
            code = reactor_client.main(["--base-url", "https://example.test", "--agent-id", "agt_test",
                                        "--history", "hist", "--question", "private-question"])
        self.assertEqual(code, 4)
        events = [json.loads(line) for line in stderr.getvalue().splitlines() if line.startswith("{")]
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertTrue(event["ack_observed"])
        self.assertTrue(event["ack_matches_sent_message"])
        self.assertEqual(event["frames"], [{"type": "ack", "cycle": 4}, {"type": "error", "code": "history_changed"}])
        self.assertEqual(event["close_code"], 1000)
        self.assertEqual(event["close_reason"], "history reset [REDACTED]")
        diagnostic = json.dumps(event)
        self.assertNotIn("private-question", diagnostic)
        self.assertNotIn("private-chat-content", diagnostic)
        self.assertNotIn("test-key", diagnostic)

    def test_clean_socket_exhaustion_records_close_reason_and_no_ack(self):
        class EmptySocket:
            close_code = 1001
            close_reason = "agent restarted"

            async def send(self, text):
                pass

            async def __aiter__(self):
                for x in []:
                    yield x

        @asynccontextmanager
        async def connect(*args, **kwargs):
            yield EmptySocket()

        with patch.object(official, "environment_problem", return_value=None), \
             patch.dict(official.os.environ, {"REACTOR_ACCESS_KEY": "test-key"}), \
             patch.object(reactor_client, "_connect", connect), \
             patch("sys.stdout", new_callable=io.StringIO) as stdout, \
             patch("sys.stderr", new_callable=io.StringIO) as stderr:
            code = reactor_client.main(["--base-url", "https://example.test", "--agent-id", "agt_test",
                                        "--history", "hist", "--question", "What?"])
        self.assertEqual(code, 5)
        event = json.loads(stderr.getvalue().splitlines()[0])
        self.assertFalse(event["ack_observed"])
        self.assertFalse(event["ack_matches_sent_message"])
        self.assertEqual(event["close_code"], 1001)
        self.assertEqual(event["close_reason"], "agent restarted")
        self.assertIn("closed the chat before an answer", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
