"""Select a reproducible five-question development diagnostic, never test data."""
import hashlib
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--answerable-only', action='store_true')
    parser.add_argument('--out', type=Path, default=Path('smoke'))
    args = parser.parse_args()
    base = Path("data/dev")
    questions = {q["question_id"]: q for q in map(json.loads, (base / "questions.jsonl").read_text().splitlines())}
    gold = list(map(json.loads, (base / "gold.jsonl").read_text().splitlines()))
    gold.sort(key=lambda q: hashlib.sha256(q["question_id"].encode()).hexdigest())
    # Include an unanswerable case plus four categories; temporal is measured offline.
    chosen = [] if args.answerable_only else [next(g for g in gold if g["abstain"])]
    categories = ["single-session-user", "single-session-assistant", "multi-session", "knowledge-update"]
    if args.answerable_only:
        categories.append('temporal-reasoning')
    for category in categories:
        chosen.append(next(g for g in gold if not g["abstain"] and g["question_type"] == category))
    out = args.out
    out.mkdir(exist_ok=True)
    for name, records in (("questions", [questions[g["question_id"]] for g in chosen]), ("gold", chosen)):
        (out / f"{name}.jsonl").write_text("".join(json.dumps(q) + "\n" for q in records))
    (out / "question_ids.txt").write_text("".join(g["question_id"] + "\n" for g in chosen))
    print("Selected 5 questions / 5 histories: 5 resets + 5 answer requests, before safe refusal retries.")
    for g in chosen:
        print(g["question_id"], g["question_type"], "unanswerable" if g["abstain"] else "answerable")


if __name__ == "__main__":
    main()
