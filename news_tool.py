#!/usr/bin/env python3
"""
news_tool.py - manager for Shole Soccer's public news.json feed.

Format kept exactly as-is:
{
  "all_news": [
    { "news_title": "...", "news_content": "...", "news_date": "24/06/2026" }
  ]
}

Usage:
    python news_tool.py                          interactive menu
    python news_tool.py add                      prompts for title + content
    python news_tool.py add -t "Patch 1.1" -c "- Fixed desync\n- New map"
    python news_tool.py list
    python news_tool.py edit 0
    python news_tool.py rm 2
    python news_tool.py validate
    python news_tool.py publish -m "news: patch 1.1"

Content: type multiple lines in the prompt, they get joined with \\n.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

# ---------------------------------------------------------------- config

NEWS_PATH = os.environ.get("NEWS_JSON", "news.json")
ROOT_KEY = "all_news"
MAX_ITEMS = 15           # trims oldest past this; set to None to keep all
INDENT = 2
DATE_FMT = "%d/%m/%Y"
AUTO_PUSH_ON_ADD = False
COMMIT_PREFIX = "news:"

T, C, D = "news_title", "news_content", "news_date"

# ---------------------------------------------------------------- io


def load():
    if not os.path.exists(NEWS_PATH):
        return []
    with open(NEWS_PATH, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    if not raw:
        return []
    data = json.loads(raw)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get(ROOT_KEY), list):
        return data[ROOT_KEY]
    raise SystemExit(f'{NEWS_PATH}: expected a "{ROOT_KEY}" array.')


def save(items):
    items = sort_items(items)
    if MAX_ITEMS:
        items = items[:MAX_ITEMS]
    tmp = NEWS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({ROOT_KEY: items}, f, ensure_ascii=False, indent=INDENT)
        f.write("\n")
    os.replace(tmp, NEWS_PATH)
    print(f"Wrote {len(items)} entries to {NEWS_PATH}")


def parse_date(s):
    try:
        return datetime.strptime(s.strip(), DATE_FMT)
    except (ValueError, AttributeError):
        return None


def sort_items(items):
    """Newest first. Unparseable dates sink to the bottom, order kept."""
    def key(pair):
        i, e = pair
        dt = parse_date(e.get(D, ""))
        return (1, 0, i) if dt is None else (0, -dt.timestamp(), i)
    return [e for _, e in sorted(enumerate(items), key=key)]


def read_content(existing=""):
    if existing:
        print("Current content:")
        for line in existing.split("\n"):
            print("  " + line)
        print("Enter new content, or blank line immediately to keep it.")
    else:
        print("Content (one line per bullet, empty line to finish):")
    lines = []
    while True:
        line = input()
        if not line.strip():
            break
        lines.append(line.rstrip())
    if not lines:
        return existing
    return "\n".join(lines)


def normalize_date(s):
    """Accepts 24/06/2026, 24.6.2026, 2026-06-24, or 'today'."""
    s = (s or "").strip().lower()
    if s in ("", "today", "tanaan", "tänään"):
        return datetime.now().strftime(DATE_FMT)
    for fmt in (DATE_FMT, "%d.%m.%Y", "%Y-%m-%d", "%d/%m/%y", "%d.%m.%y"):
        try:
            return datetime.strptime(s, fmt).strftime(DATE_FMT)
        except ValueError:
            continue
    raise SystemExit(f"Unrecognized date: {s!r} (use DD/MM/YYYY)")


# ---------------------------------------------------------------- commands


def cmd_add(args):
    items = load()

    title = args.title or input("Title: ").strip()
    if not title:
        raise SystemExit("Title is required.")

    if args.content is not None:
        content = args.content.replace("\\n", "\n")
    else:
        content = read_content()

    date = normalize_date(args.date)

    items.insert(0, {T: title, C: content, D: date})
    save(items)
    print(f"Added: {title} ({date})")

    if args.push or AUTO_PUSH_ON_ADD:
        git_publish(f"{COMMIT_PREFIX} {title}")


def cmd_list(args=None):
    items = load()
    if not items:
        print("(no entries)")
        return
    for i, e in enumerate(items):
        print(f"\n[{i}] {e.get(D, '??/??/????')}  {e.get(T, '(no title)')}")
        for line in e.get(C, "").split("\n"):
            print("     " + line)


def pick(items, ref):
    if ref.isdigit():
        idx = int(ref)
        if idx >= len(items):
            raise SystemExit("Index out of range.")
        return idx
    matches = [i for i, e in enumerate(items)
               if ref.lower() in e.get(T, "").lower()]
    if not matches:
        raise SystemExit(f"No entry matching {ref!r}")
    if len(matches) > 1:
        raise SystemExit(f"{ref!r} matches {len(matches)} entries; use the index.")
    return matches[0]


def cmd_edit(args):
    items = load()
    idx = pick(items, args.ref)
    e = items[idx]

    new_title = input(f"Title [{e.get(T, '')}]: ").strip()
    if new_title:
        e[T] = new_title
    e[C] = read_content(e.get(C, ""))
    new_date = input(f"Date [{e.get(D, '')}]: ").strip()
    if new_date:
        e[D] = normalize_date(new_date)

    save(items)
    print(f"Updated: {e[T]}")


def cmd_rm(args):
    items = load()
    idx = pick(items, args.ref)
    removed = items.pop(idx)
    save(items)
    print(f"Removed: {removed.get(T)}")


def cmd_validate(args=None):
    items = load()
    problems = []
    for i, e in enumerate(items):
        for field in (T, C, D):
            if field not in e:
                problems.append(f"[{i}] missing {field}")
        for field in e:
            if field not in (T, C, D):
                problems.append(f"[{i}] unexpected field: {field}")
        if D in e and parse_date(e[D]) is None:
            problems.append(f"[{i}] bad date (want DD/MM/YYYY): {e[D]!r}")
        if not e.get(T, "").strip():
            problems.append(f"[{i}] empty title")

    size = os.path.getsize(NEWS_PATH) if os.path.exists(NEWS_PATH) else 0
    print(f"{len(items)} entries, {size} bytes")
    if problems:
        print("\n".join(problems))
        sys.exit(1)
    print("OK - valid JSON, schema matches.")


def git(*a):
    return subprocess.run(
        ["git", *a],
        cwd=os.path.dirname(os.path.abspath(NEWS_PATH)) or ".",
        check=True,
    )


def git_publish(message):
    try:
        git("add", os.path.basename(NEWS_PATH))
        git("commit", "-m", message)
        git("push")
        print("Pushed.")
    except subprocess.CalledProcessError as e:
        print(f"git failed (exit {e.returncode}) - commit/push manually.")


def cmd_publish(args):
    today = datetime.now().strftime(DATE_FMT)
    git_publish(args.message or f"{COMMIT_PREFIX} update {today}")


# ---------------------------------------------------------------- menu


def interactive():
    while True:
        print("\n1) add  2) list  3) edit  4) remove  5) validate  6) publish  0) quit")
        choice = input("> ").strip()
        try:
            if choice == "1":
                cmd_add(argparse.Namespace(title=None, content=None,
                                           date=None, push=False))
            elif choice == "2":
                cmd_list()
            elif choice == "3":
                cmd_list()
                cmd_edit(argparse.Namespace(ref=input("\nindex or title: ").strip()))
            elif choice == "4":
                cmd_list()
                cmd_rm(argparse.Namespace(ref=input("\nindex or title: ").strip()))
            elif choice == "5":
                cmd_validate()
            elif choice == "6":
                msg = input("commit msg (blank = default): ").strip()
                cmd_publish(argparse.Namespace(message=msg or None))
            elif choice in ("0", "q", ""):
                return
        except SystemExit as e:
            print(e)
        except KeyboardInterrupt:
            return


def main():
    global NEWS_PATH
    p = argparse.ArgumentParser(description="Manage news.json")
    p.add_argument("-f", "--file", help="path to news.json")
    sub = p.add_subparsers(dest="cmd")

    a = sub.add_parser("add")
    a.add_argument("-t", "--title")
    a.add_argument("-c", "--content", help=r"use \n for line breaks")
    a.add_argument("-d", "--date", help="DD/MM/YYYY, default today")
    a.add_argument("--push", action="store_true")
    a.set_defaults(func=cmd_add)

    sub.add_parser("list").set_defaults(func=cmd_list)

    ed = sub.add_parser("edit")
    ed.add_argument("ref", help="index or part of the title")
    ed.set_defaults(func=cmd_edit)

    rm = sub.add_parser("rm")
    rm.add_argument("ref", help="index or part of the title")
    rm.set_defaults(func=cmd_rm)

    sub.add_parser("validate").set_defaults(func=cmd_validate)

    pb = sub.add_parser("publish")
    pb.add_argument("-m", "--message")
    pb.set_defaults(func=cmd_publish)

    args = p.parse_args()
    if args.file:
        NEWS_PATH = args.file
    if not args.cmd:
        interactive()
    else:
        args.func(args)


if __name__ == "__main__":
    main()
