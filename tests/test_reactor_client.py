import io
import json
import unittest
from contextlib import asynccontextmanager
from unittest.mock import patch

from official.reactor import client as official
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

    def test_prompt_requires_labels_on_final_line_and_preserves_dates(self):
        prompt = reactor_client.build_message("What is my cat's name?", self.evidence,
                                             "1234abcd", "2023-05-30 12:18")
        self.assertIn("final answer line itself MUST include", prompt)
        self.assertIn("A citation anywhere before the final answer line does not count", prompt)
        self.assertIn("Use only labels supplied in this question: [E1]", prompt)
        self.assertIn("date: 2023/05/20 (Sat) 02:21", prompt)
        self.assertIn("Question date: 2023-05-30 (Tue) 12:18", prompt)
        self.assertIn("INSUFFICIENT_EVIDENCE", prompt)

    def test_main_wraps_prompt_only_and_restores_official_function(self):
        original = official.build_message
        def fake_main(argv):
            self.assertIs(official.build_message, reactor_client.build_message)
            self.assertEqual(argv, ["--help"])
            return 0
        with patch.object(official, "main", side_effect=fake_main):
            self.assertEqual(reactor_client.main(["--help"]), 0)
        self.assertIs(official.build_message, original)

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
