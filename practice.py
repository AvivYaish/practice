#!/usr/bin/env python3
# Installation: Python 3.9+ and `python -m pip install "prompt_toolkit>=3.0.52,<4"`
# Usage: `python practice.py`

from collections import Counter, defaultdict
from contextlib import suppress
from datetime import datetime, timezone
from functools import partial
import json, random, re, sys, time
from pathlib import Path

BANK = Path(__file__).with_name("db.json")
EXCLUDED = (("tag", "Unreliable"), ("tag", "AI"))
HISTORY = (("Wrong", "wrong", True), ("Skipped", "skipped", True), ("Unviewed", "viewed", False))

class EndTest(Exception):
    pass

def save(data, path=None):
    path = path or BANK
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)

def now():
    return datetime.now(timezone.utc).isoformat()

def reset(data, category):
    field = "viewed" if category == "unviewed" else category
    for row in data.setdefault("tracking", {}).values():
        row.pop(field, None)
    save(data)
    return f"Reset {category.capitalize()}."

def note(q):
    pages = q.get("validation", {}).get("pages", [])
    return "Note\n" + (q.get("note") or "No note.") + ("\nManual pages: " + ", ".join(map(str, pages)) if pages else "")

def build_html(data):
    page = BANK.with_name("practice.html")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    html, count = re.subn(r'(<script id="data" type="application/json">).*?(</script>)', lambda m: m[1] + payload + m[2], page.read_text(encoding="utf-8"), count=1, flags=re.S)
    if not count:
        raise ValueError("practice.html is missing its data block.")
    page.write_text(html, encoding="utf-8")
    return f"Updated {page.name}."

def choose(started, q, position, misses, navigate=True, choice=-1, back=True):
    try:
        from prompt_toolkit import Application
        from prompt_toolkit.application.current import get_app
        from prompt_toolkit.data_structures import Point
        from prompt_toolkit.filters import Condition
        from prompt_toolkit.formatted_text import fragment_list_to_text
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import ConditionalContainer, Dimension, DynamicContainer, FormattedTextControl, HSplit, Layout, ScrollbarMargin, VSplit, Window, WindowAlign
        from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType
        from prompt_toolkit.styles import Style
        from prompt_toolkit.utils import get_cwidth
        from prompt_toolkit.widgets import Frame, HorizontalLine, Label, RadioList
    except ImportError:
        raise SystemExit('Install once: python -m pip install "prompt_toolkit>=3.0.52,<4"') from None
    class Scrollbar(ScrollbarMargin):
        def create_margin(self, info, width, height):
            return super().create_margin(info, width, height) if overflow(info) else []
    locked, states, shown = choice != -1, q.get("states"), set()
    message, line, note_line = q.get("message"), 0, 0
    separator = ("class:muted", "|")
    moves = ("up", "down", "home", "end", "pageup", "pagedown")

    def move(key, current, last, page, wrap=False):
        target = 0 if key == "home" else last if key == "end" else current + {"up": -1, "down": 1, "pageup": -page, "pagedown": page}[key]
        return target % (last + 1) if wrap and key in ("up", "down") else max(0, min(last, target))
    def overflow(info):
        return max(0, sum(info.get_height_for_line(i) for i in range(info.content_height)) - info.window_height) if info else 0
    def scroll(window, key, current):
        return move(key, current, overflow(window.render_info), max(1, window.render_info.window_height - 1) if window.render_info else 1)

    def cursor(window, offset):
        info, remaining = window.render_info, offset
        if info:
            for row in range(info.content_height):
                height = info.get_height_for_line(row)
                if remaining < height:
                    window.vertical_scroll, window.vertical_scroll_2 = row, remaining
                    text, column, x = fragment_list_to_text(info.ui_content.get_line(row)), remaining * info.window_width + bool(remaining), 0
                    while x < len(text) and column > 0:
                        column -= get_cwidth(text[x])
                        x += 1
                    return Point(x, row)
                remaining -= height
        return Point(0, 0)
    def text_window(text, offset):
        window = Window(FormattedTextControl(text, focusable=True, get_cursor_position=lambda: cursor(window, offset())), wrap_lines=True, always_hide_cursor=True, right_margins=[Scrollbar(display_arrows=True)])
        return window
    def option(i, text):
        if states and i:
            return [("class:excluded" if states[i] == "-" else "", "-"), ("class:included" if states[i] == "+" else "", "+"), ("", text[2:])]
        return marked(text, i == q["answer"]) if "answer" in shown and q["answer"] is not None and i in (q["answer"], choice) else text
    options = RadioList([(i, partial(option, i, text)) for i, text in enumerate(q["choices"])], default=q.get("selected", choice), select_on_focus=True, open_character="", select_character=">", close_character="", show_numbers=True, show_cursor=False, show_scrollbar=False)
    options.window.wrap_lines = Condition(lambda: True)
    bindings = KeyBindings()
    def status():
        return [("", "%02d:%02d" % divmod(max(0, int(time.monotonic() - started)), 60)), separator, ("", position.replace(" ", "")), separator, button(f"Wrong: {len(misses)}", "7")]

    def handle(key, event, enabled=True):
        nonlocal message, line, note_line
        key = dict(w="up", a="left", s="down", d="right").get(key.lower(), key)
        if not enabled or isinstance(event, MouseEvent) and (event.button != MouseButton.LEFT or event.event_type != MouseEventType.MOUSE_UP):
            return NotImplemented
        app = get_app()
        if app.is_done:
            return
        if key in ("c-c", "<sigint>", "0"):
            app.exit(exception=KeyboardInterrupt() if key != "0" else EndTest() if navigate else SystemExit())
        elif message:
            if key in moves:
                line = scroll(message_window, key, line)
            elif key in ("enter", " ", "right", "left", "escape"):
                if "message" in q:
                    app.exit()
                message = None
                app.layout.focus(options)
        elif key == "escape" or key == "left" and back:
            abort = not navigate or key == "escape"
            app.exit(result=None if abort else "back", exception=EndTest() if abort else None)
        elif navigate and key == "7":
            message, line = review(misses), 0
            app.layout.focus(message_window)
        elif navigate and key in ("8", "9"):
            shown.add("note" if key == "8" else "answer")
        elif key in moves and "note" in shown and overflow(note_window.render_info):
            note_line = scroll(note_window, key, note_line)
        elif key in moves and not locked:
            info = options.window.render_info
            options._selected_index = options.current_value = move(key, options._selected_index, len(options.values) - 1, max(1, len(set(info.displayed_lines)) - 1) if info else 1, wrap=True)
        elif states and (key in ("enter", " ", "right") or key in ("-", "+") and options.current_value):
            app.exit(result=(options.current_value, "next" if key == "right" else "cycle" if key in ("enter", " ") else key))
        elif key in ("enter", " ", "right") or key.isdecimal() and 0 < int(key) <= len(q["choices"]) and not locked:
            app.exit(result="next" if locked else int(key) - 1 if key.isdecimal() else options.current_value)

    def button(text, key, enabled=True):
        shortcut = {"left": "←", "right": "→"}.get(key, key)
        return ("class:button" if enabled else "class:muted", f"{text}({shortcut})", partial(handle, key, enabled=enabled))

    rows = [i for i, text in enumerate(q["choices"]) for _ in range(text.count("\n") + 1)]
    def click(event):
        if not 0 <= event.position.y < len(rows):
            return NotImplemented
        i = rows[event.position.y]
        if states and event.button == MouseButton.LEFT and event.event_type == MouseEventType.MOUSE_UP:
            options._selected_index = options.current_value = i
            column = event.position.x - len(f"{i + 1:2d}. ") - 2
            if i and column in (0, 1):
                return handle("-+"[column], event)
            return handle("enter", event)
        return handle(str(i + 1), event)
    options.control.mouse_handler = click

    def mouse(app):
        original = app.renderer.mouse_handlers.mouse_handlers
        def dispatch(event):
            if event.event_type in (MouseEventType.SCROLL_UP, MouseEventType.SCROLL_DOWN):
                return handle("up" if event.event_type == MouseEventType.SCROLL_UP else "down", None)
            return original[event.position.y][event.position.x](event)
        app.renderer.mouse_handlers.mouse_handlers = defaultdict(lambda: defaultdict(lambda: dispatch))
    for key in ["enter", " ", *moves, "left", "right", "escape", "c-c", "<sigint>", *"0123456789-+wasdWASD"]:
        bindings.add(key, eager=True)(partial(handle, key))

    def section(text, visible, style=""):
        return ConditionalContainer(HSplit([HorizontalLine(), text if isinstance(text, Window) else Label(text, style=style)]), filter=Condition(visible))
    message_window, note_window = text_window(lambda: message or "", lambda: line), text_window(lambda: note(q), lambda: note_line)
    body = [Label(q["question"], style="bold"), options, section("Tags: " + ", ".join(q.get("tags") or []), lambda: bool(q.get("tags")), "class:muted"), section(lambda: details(q, choice, "answer" in shown), lambda: choice != -1 or "answer" in shown), section(note_window, lambda: "note" in shown)]
    actions = lambda: [button("Note", "8", not message), separator, button("Reveal", "9", not message and "answer" not in shown), separator, button("End", "0")] if navigate else [button("Exit", "0")]
    navigation = [("class:muted", "│ "), button("Back", "left", back), separator, button("Next", "right"), ("class:muted", " │")]
    nav_width = sum(len(part[1]) for part in navigation)
    blocks = [Label(status if navigate else "", style="bold", width=Dimension(preferred=0)), Label(navigation, width=nav_width, align=WindowAlign.CENTER), Label(actions, width=Dimension(preferred=0), align=WindowAlign.RIGHT)]
    minimum = 2 * max(sum(len(part[1]) for part in parts) for parts in (status() if navigate else [], actions())) + nav_width + 2
    header = DynamicContainer(lambda: VSplit(blocks, padding=1) if get_app().output.get_size().columns >= minimum else HSplit(blocks))
    layout = Layout(HSplit([header, Frame(DynamicContainer(lambda: message_window if message else HSplit(body)), title="Practice Test"), Window(FormattedTextControl(q.get("notice", "")), height=1, style="class:muted")]), focused_element=message_window if message else options)
    style = Style.from_dict({"frame.border": "#6589bd", "radio-selected": "bg:#17345f #ffffff bold", "button": "bg:#17345f #ffffff", "included": "bg:#18703a #ffffff bold", "excluded": "bg:#70333d #ffffff bold", "muted": "#888888", "horizontal-line": "#888888"})
    return Application(layout=layout, key_bindings=bindings, style=style, refresh_interval=0.25, after_render=mouse, full_screen=True, erase_when_done=True, mouse_support=True).run()

def marked(text, correct):
    return [("ansigreen bold" if correct else "ansired bold", "✓ " if correct else "✗ "), ("", text)]

def details(q, choice=-1, show_key=True):
    answer = q["answer"]
    text = "" if choice == -1 else f"Choice: {q['choices'][choice]}\n"
    lines = marked(text, choice == answer) if show_key and answer is not None and choice != -1 else [("", text)]
    return lines + ([] if not show_key else [("", "Answer: Not verified.")] if answer is None else marked(f"Answer: {q['choices'][answer]}", True))

def review(misses):
    heading = [("bold", f"Wrong: {len(misses)}\n"), ("", "" if misses else "No wrong answers in this session.\n")]
    return heading + [part for q, chosen in misses for part in [("", f"\n{q['question']}\n"), *details(q, chosen), ("", "\n")]]

def message(text):
    choose(None, dict(question="", choices=[""], message=text), "", [], navigate=False)

def session(questions, answers):
    return [(q, choice) for q, choice in zip(questions, answers) if q["answer"] is not None and choice not in (-1, q["answer"])]

def test(data, bank):
    if not bank:
        return message("No questions match these filters.")
    tracking = data.setdefault("tracking", {})
    count, index, started = len(bank), 0, time.monotonic()
    questions, answers = random.sample(bank, count), [-1] * count
    total = sum(q["answer"] is not None for q in questions)
    with suppress(EndTest):
        while 0 <= index < count:
            q = questions[index]
            tracking.setdefault(q["id"], {}).setdefault("viewed", now())
            chosen = choose(started, q, f"{index + 1} / {count}", session(questions, answers), choice=answers[index])
            if chosen in ("back", "next"):
                index += -1 if chosen == "back" else 1
                continue
            answers[index] = chosen
            if q["answer"] is not None and chosen != q["answer"]:
                tracking[q["id"]].setdefault("wrong", []).append({"at": now(), "answer": q["choices"][chosen]})
            index += 1
    save(data)
    if index < 0:
        return
    correct = sum(q["answer"] is not None and choice == q["answer"] for q, choice in zip(questions, answers))
    unviewed = sum(not tracking.get(q["id"], {}).get("viewed") for q in data["questions"])
    text = [("bold", ("Completed" if not total else "Passed" if correct >= 0.8 * total else "Keep practicing") + "\n"), ("", f"{correct} of {total} correct." + (" Ended early." if index < count else "") + "\n\n"), *review(session(questions, answers)), ("", "\n"), ("bold", f"Unviewed: {unviewed}")]
    message(text)

def menu(title, labels, end="Back", selected=-1, states=None, notice=""):
    with suppress(EndTest):
        return choose(None, dict(question=title, choices=labels, selected=selected, states=states, notice=notice), "", [], navigate=False, back=end == "Back")

def filters_for(q, tracking):
    row = tracking.get(q["id"], {})
    return {("history", title) for title, field, present in HISTORY if bool(row.get(field)) == present} | {("tag", t) for t in q.get("tags") or []} | {("source", s["name"]) for s in q.get("sources", []) if s.get("name")}

def pool(bank, included=(), excluded=EXCLUDED, tracking=None):
    included, excluded, tracking = set(included), set(excluded), tracking or {}
    history = {t for t in included if t[0] == "history"}
    tags = included - history
    return [q for q in bank if not (excluded & (filters := filters_for(q, tracking))) and (not history or filters & history) and (not tags or filters & tags)]

def filter_menu(bank, tracking, included, excluded):
    counts, chosen = Counter(t for q in bank for t in filters_for(q, tracking)), 0
    filters = [("history", title) for title, _, _ in HISTORY] + sorted((t for t in counts if t[0] != "history"), key=lambda t: (t[0] != "tag", t[1]))
    while True:
        labels = [f"All ({len(pool(bank, excluded=excluded, tracking=tracking))})"] + [f"-+ {t[1]} ({counts[t]})" for t in filters]
        states = [""] + ["-" if t in excluded else "+" if t in included else "" for t in filters]
        action = menu("Filters: - exclude, + include", labels, selected=chosen, states=states)
        if action is None:
            return
        chosen, sign = action if isinstance(action, tuple) else (action, "")
        sign = {"": "+", "+": "-", "-": ""}[states[chosen]] if sign == "cycle" else sign
        if chosen == 0:
            included.clear()
        else:
            tag = filters[chosen - 1]
            included.discard(tag)
            excluded.discard(tag)
            if sign and states[chosen] != sign:
                (excluded if sign == "-" else included).add(tag)
        if sign == "next":
            return

def main():
    data = json.loads(BANK.read_text(encoding="utf-8-sig"))
    bank, tracking = data["questions"], data.setdefault("tracking", {})
    included, excluded = set(), set(EXCLUDED)
    if any(not 2 <= len(q["choices"]) <= 4 or q["answer"] is not None and (type(q["answer"]) is not int or q["answer"] not in range(len(q["choices"]))) for q in bank):
        raise ValueError("Each question needs 2-4 choices and a valid answer index or null.")
    if not sys.stdin.isatty():
        raise ValueError("Run this script in an interactive terminal.")
    notice = ""
    with suppress(KeyboardInterrupt):
        while (action := menu(f"Questions: {len(pool(bank, included, excluded, tracking))}", ["Start", "Reset", "Filters", "Build HTML"], end="Exit", notice=notice)) is not None:
            notice = ""
            if action == 0:
                test(data, pool(bank, included, excluded, tracking))
            elif action == 1:
                selected, status = 0, ""
                while (selected := menu("Reset", [f"{title} ({len(pool(bank, [('history', title)], (), tracking))})" for title, _, _ in HISTORY], selected=selected, notice=status)) is not None:
                    status = reset(data, HISTORY[selected][0].lower())
            elif action == 2:
                filter_menu(bank, tracking, included, excluded)
            else:
                notice = build_html(data)

if __name__ == "__main__":
    main()
