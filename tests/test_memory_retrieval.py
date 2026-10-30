import unittest

from retrieval_memory import _cards, retrieve


class MemoryRetrievalTests(unittest.TestCase):
    def history(self, date='2026/01/01'):
        return {'history_id': 'h', 'sessions': [
            {'session_id': 's1', 'date': date, 'turns': [
                {'turn_id': 't1', 'role': 'user', 'content': 'I graduated with a degree in marine biology. My commute takes forty minutes.'},
                {'turn_id': 't2', 'role': 'assistant', 'content': 'Marine biology studies life in the ocean.'}]},
            {'session_id': 's2', 'date': date, 'turns': [
                {'turn_id': 't3', 'role': 'user', 'content': 'I bought a coffee on Tuesday.'}]}]}

    def test_verbatim_and_source(self):
        for method in ('memory', 'memory-facts'):
            rows = retrieve({'question': 'What degree did I graduate with?'}, self.history(), k=1, method=method)
            self.assertEqual(rows[0]['id'], 's1')
            self.assertIn('user [t1]: I graduated with a degree in marine biology.', rows[0]['text'])

    def test_memory_snippets_are_source_substrings(self):
        content = 'I spent $3.50.\nMy receipt has arrived. This remains my exact wording.'
        for text, _, _, _ in _cards('user', 't', content):
            self.assertIn(text, content)

    def test_cached_content_uses_current_history_dates(self):
        question = {'question': 'What degree?'}
        retrieve(question, self.history('old'))
        rows = retrieve(question, self.history('new'))
        self.assertTrue(all(row['date'] == 'new' for row in rows))

    def test_budget_and_distinct_sessions(self):
        rows = retrieve({'question': 'marine biology coffee'}, self.history(), k=4, budget=80)
        self.assertLessEqual(sum(len(row['text']) for row in rows), 80)
        self.assertEqual(len({row['id'] for row in rows}), len(rows))

    def test_invalid_config_and_empty_history(self):
        with self.assertRaises(ValueError):
            retrieve({'question': 'degree'}, self.history(), method='bad')
        self.assertEqual(retrieve({'question': 'degree'}, {'sessions': []}), [])


if __name__ == '__main__':
    unittest.main()
