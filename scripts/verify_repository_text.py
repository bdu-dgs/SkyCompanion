#!/usr/bin/env python3
"""Check candidate repository paths and text for English-only project handoff."""
from pathlib import Path
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
HAN = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f]")
OLD_BRAND = re.compile(r"(?<![A-Za-z0-9])[eE][vV][aA](?=$|[^A-Za-z0-9]|[A-Z][a-z])")


def main():
    paths = set(subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
        cwd=ROOT,
    ).decode().split('\0'))
    findings = []
    checked = 0
    for relative in sorted(paths):
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            continue
        if HAN.search(relative) or OLD_BRAND.search(relative):
            findings.append({'file': relative, 'issue': 'nonconforming path'})
        try:
            content = path.read_text(encoding='utf-8')
        except UnicodeError:
            continue
        if '\0' in content:
            continue
        checked += 1
        if path.suffix in {'.json', '.xcstrings'}:
            try:
                content = json.dumps(json.loads(content), ensure_ascii=False)
            except ValueError:
                pass
        if HAN.search(content):
            findings.append({'file': relative, 'issue': 'non-English Han text'})
        if OLD_BRAND.search(content):
            findings.append({'file': relative, 'issue': 'old project identity'})
    print(json.dumps({'checked_text_files': checked, 'findings': findings}, indent=2))
    return bool(findings)


if __name__ == '__main__':
    sys.exit(main())
