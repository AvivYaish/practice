#!/usr/bin/env python3
# Usage: in the same folder as practice.py and db.json, run `python edit.py`

from copy import deepcopy
import json
from uuid import uuid4
from practice import BANK, build_html, menu, now, save

try:
    from prompt_toolkit import prompt
    from prompt_toolkit.key_binding import KeyBindings
except ImportError:
    raise SystemExit('Install once: python -m pip install "prompt_toolkit>=3.0.52,<4"') from None

class Cancel(Exception):
    pass

keys = KeyBindings()
keys.add("escape")(lambda event: event.app.exit(exception=Cancel()))

def ask(label, value="", valid=lambda text: True):
    while True:
        text = prompt(label, default=str(value), key_bindings=keys).strip()
        if valid(text):
            return text
        print("Invalid value.")

def record(data, ids=()):
    metadata = data.setdefault("metadata", {})
    metadata["edits"] = list(dict.fromkeys([*metadata.get("edits", []), *ids]))
    metadata["edited_on"] = now()

def validate(q):
    choices, answer, tags = q.get("choices"), q.get("answer"), q.get("tags", [])
    if any(not isinstance(q.get(key), str) or not q[key].strip() for key in ("id", "question")):
        raise ValueError("A question needs an ID and text.")
    if not isinstance(choices, list) or not 2 <= len(choices) <= 4 or any(not isinstance(c, str) or not c.strip() for c in choices) or len({" ".join(c.split()).casefold() for c in choices}) != len(choices):
        raise ValueError("Use 2-4 distinct, nonblank choices.")
    if answer is not None and (type(answer) is not int or answer not in range(len(choices))):
        raise ValueError("Answer must be a choice index or null.")
    if not isinstance(tags, list) or any(not isinstance(t, str) or not t.strip() for t in tags):
        raise ValueError("Tags must be nonblank text.")

def put_question(data, candidate):
    old = next((q for q in data["questions"] if q["id"] == candidate.get("id")), None)
    q = deepcopy({**(old or dict(topic="", tags=[], sources=[], note="", validation={"status": "not_checked"})), **candidate})
    validate(q)
    q["tags"] = list(dict.fromkeys(q.get("tags", [])))
    if old and any(q[k] != old[k] for k in ("question", "choices", "answer")):
        q.setdefault("validation", {})["status"] = "not_checked"
        reminder = "Edited locally. Recheck the answer."
        if reminder not in q.get("note", ""):
            q["note"] = (q.get("note", "") + "\n" + reminder).strip()
    if old:
        data["questions"][data["questions"].index(old)] = q
    else:
        data["questions"].append(q)
    record(data, [q["id"]])

def delete_question(data, identifier):
    data["questions"] = [q for q in data["questions"] if q["id"] != identifier]
    data.setdefault("tracking", {}).pop(identifier, None)
    record(data, [identifier])

def tag_change(data, old, new=None, description=None):
    definitions = data.setdefault("metadata", {}).setdefault("tag_definitions", {})
    names = set(definitions) | {t for q in data["questions"] for t in q.get("tags", [])}
    if new is not None and (not isinstance(new, str) or not new.strip()):
        raise ValueError("A tag needs a name.")
    if old is None and new in names:
        raise ValueError("Tag already exists.")
    if old is not None and old not in names:
        raise ValueError("Tag not found.")
    if old == new and (description is None or description == definitions.get(old, "")):
        return False
    previous = definitions.pop(old, "") if old != new else definitions.get(old, "")
    if new is not None:
        definitions[new] = description if description is not None else definitions.get(new, previous)
    affected = [q for q in data["questions"] if old is not None and old != new and old in q.get("tags", [])]
    for q in affected:
        q["tags"] = list(dict.fromkeys(new if t == old else t for t in q["tags"] if t != old or new is not None))
    record(data, (q["id"] for q in affected))
    return True

def commit(data):
    save(data)
    print("Saved db.json.")
    if BANK.with_name("practice.html").exists():
        build_html(data)

def question_form(data, original=None):
    q = deepcopy(original) if original else dict(id="LOCAL-" + uuid4().hex, question="", choices=[""] * 4, answer=None, tags=[])
    while not original and any(row["id"] == q["id"] for row in data["questions"]):
        q["id"] = "LOCAL-" + uuid4().hex
    q["question"] = ask("Question: ", q["question"], bool)
    count = int(ask("Choices (2-4): ", len(q["choices"]), lambda text: text in ("2", "3", "4")))
    q["choices"] = [ask(f"Choice {i + 1}: ", q["choices"][i] if i < len(q["choices"]) else "", bool) for i in range(count)]
    answer = ask(f"Answer (1-{count}, blank = Unscored): ", "" if q["answer"] is None else q["answer"] + 1, lambda text: not text or text in map(str, range(1, count + 1)))
    q["answer"] = int(answer) - 1 if answer else None
    q["topic"] = ask("Topic: ", q.get("topic", ""))
    q["tags"] = [t.strip() for t in ask("Tags (comma-separated): ", ", ".join(q["tags"])).split(",") if t.strip()]
    q["note"] = ask("Note: ", q.get("note", ""))
    if menu("Save question?", ["Save", "Cancel"]) == 0:
        put_question(data, q)
        commit(data)

def pick_question(data):
    query = ask("Search (blank = all): ").casefold()
    matches = [q for q in data["questions"] if query in json.dumps(q, ensure_ascii=False).casefold()]
    if not matches:
        print("No questions found.")
        return
    chosen = menu("Questions", [q["id"] + "  " + q["question"].replace("\n", " ")[:110] for q in matches])
    return matches[chosen] if chosen is not None else None

def tags(data):
    definitions = data.get("metadata", {}).get("tag_definitions", {})
    action = menu("Tags", ["Create", "Edit", "Delete"])
    if action is None:
        return
    old = None
    if action:
        names = sorted(set(definitions) | {t for q in data["questions"] for t in q.get("tags", [])})
        if not names:
            print("No tags.")
            return
        chosen = menu("Tags", names)
        if chosen is None:
            return
        old = names[chosen]
    new = None if action == 2 else ask("Name: ", old or "", bool)
    description = None if action == 2 else ask("Description: ", definitions.get(new, definitions.get(old, "")))
    if menu("Delete tag everywhere?" if action == 2 else "Save tag?", ["Cancel", "Delete" if action == 2 else "Save"]) == 1 and tag_change(data, old, new, description):
        commit(data)

def main():
    data = json.loads(BANK.read_text(encoding="utf-8-sig"))
    try:
        while (action := menu("Database editor", ["Create question", "Edit question", "Delete question", "Tags"], end="Exit")) is not None:
            try:
                if action == 0:
                    question_form(data)
                elif action == 3:
                    tags(data)
                elif (q := pick_question(data)) is not None:
                    if action == 1:
                        question_form(data, q)
                    elif menu("Delete this question?", ["Cancel", "Delete"]) == 1:
                        delete_question(data, q["id"])
                        commit(data)
            except Cancel:
                print("Cancelled.")
            except ValueError as error:
                print(error)
    except (KeyboardInterrupt, EOFError):
        print("\nExited without saving the current edit.")

if __name__ == "__main__":
    main()
