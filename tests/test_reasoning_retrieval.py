"""Gold-free selection, complementary anchors and evidence packing contracts."""
import unittest

from retrieval_reasoning import METHODS, _anchors, retrieve


class ReasoningRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.history = {'sessions': [
            {'session_id': 's_a', 'date': '2023/01/01', 'turns': [
                {'role': 'user', 'content': 'I attended the Museum of Modern Art exhibit.'},
                {'role': 'assistant', 'content': 'The Museum of Modern Art exhibit sounds excellent.'},
                {'role': 'user', 'content': 'The Museum of Modern Art exhibit was fun.'},
                {'role': 'assistant', 'content': 'Museum of Modern Art exhibit.'}]},
            {'session_id': 's_b', 'date': '2023/01/08', 'turns': [
                {'role': 'user', 'content': 'I visited the Ancient Civilizations exhibit at the Metropolitan Museum.'}]},
            {'session_id': 's_c', 'date': '2023/02/01', 'turns': [
                {'role': 'user', 'content': 'I made a chocolate cake.'}]}]}
        self.question = {'question': 'How many days passed between my Museum of Modern Art exhibit visit and my Ancient Civilizations exhibit at the Metropolitan Museum?'}

    def test_two_anchor_complement_replaces_duplicate_turns(self):
        anchors = _anchors(self.question['question'])
        self.assertEqual(len(anchors), 2)
        result = retrieve(self.question, self.history, k=2)
        self.assertEqual({r['id'] for r in result}, {'s_a', 's_b'})

    def test_never_reads_gold_or_question_type(self):
        enriched = dict(self.question, question_type='single-session-user', answer='wrong', evidence=['invented'], question_id='anything')
        for method in METHODS:
            self.assertEqual(retrieve(enriched, self.history, method=method), retrieve(self.question, self.history, method=method))

    def test_simple_question_keeps_baseline_session_set(self):
        from retrieval import retrieve as baseline
        question = {'question': 'Which Museum of Modern Art exhibit did I attend?'}
        self.assertEqual({r['id'] for r in retrieve(question, self.history)}, {r['id'] for r in baseline(question, self.history)})

    def test_budgets_roles_ids_dates_no_mutation(self):
        import copy
        original = copy.deepcopy(self.history)
        for method in METHODS:
            for budget in (1, 7, 35, 101, 12000):
                result = retrieve(self.question, self.history, budget=budget, method=method)
                self.assertLessEqual(sum(len(r['text']) for r in result), budget)
                self.assertEqual(len(result), len({r['id'] for r in result}))
                self.assertLessEqual(len(result), 4)
                for row in result:
                    source = next(s for s in self.history['sessions'] if s['session_id'] == row['id'])
                    self.assertEqual(row['date'], source['date'])
                    if budget == 12000:
                        self.assertIn('user:', row['text'])
        self.assertEqual(self.history, original)

    def test_no_history_date_or_id_cross_contamination(self):
        import copy
        other = copy.deepcopy(self.history)
        other['sessions'][0]['session_id'] = 'new_id'
        other['sessions'][0]['date'] = '2030/05/04'
        result = retrieve(self.question, other)
        self.assertIn(('new_id', '2030/05/04'), [(r['id'], r['date']) for r in result])

    def test_empty_irrelevant_invalid(self):
        self.assertEqual(retrieve({'question': 'quasar'}, self.history), [])
        self.assertEqual(retrieve(self.question, {'sessions': []}), [])
        for kwargs in ({'k': 0}, {'budget': 0}, {'method': 'unknown'}):
            with self.assertRaises(ValueError):
                retrieve(self.question, self.history, **kwargs)


if __name__ == '__main__':
    unittest.main()
