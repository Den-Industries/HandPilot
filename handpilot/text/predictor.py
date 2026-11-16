"""Word completion from frequency lists, with learning of the user's own words."""
from __future__ import annotations

import bisect
import json
import os
import threading

from ..config import ASSETS_DIR, config_dir

WORDLIST_DIR = os.path.join(ASSETS_DIR, "wordlists")


class WordPredictor:
    def __init__(self, lang: str):
        self.lang = lang
        self.freq: dict[str, float] = {}
        self.sorted_words: list[str] = []
        self.user_path = os.path.join(config_dir(), f"user_words_{lang}.json")
        self.user: dict[str, int] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        path = os.path.join(WORDLIST_DIR, f"{self.lang}.txt")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) == 2:
                        self.freq[parts[0]] = float(parts[1])
        try:
            with open(self.user_path, encoding="utf-8") as f:
                self.user = {k: int(v) for k, v in json.load(f).items()}
        except (OSError, ValueError):
            self.user = {}
        self.sorted_words = sorted(set(self.freq) | set(self.user))

    def _score(self, w: str) -> float:
        # A word the user typed a few times beats the generic list.
        top = max(self.freq.values(), default=1.0)
        return self.freq.get(w, 0.0) + self.user.get(w, 0) * top * 0.02

    def suggest(self, prefix: str, n: int = 3) -> list[str]:
        p = prefix.lower()
        if not p:
            return []
        with self._lock:
            i = bisect.bisect_left(self.sorted_words, p)
            cands = []
            while i < len(self.sorted_words) and self.sorted_words[i].startswith(p):
                cands.append(self.sorted_words[i])
                i += 1
                if len(cands) > 4000:
                    break
        cands = [w for w in cands if w != p] or cands
        cands.sort(key=self._score, reverse=True)
        out = cands[:n]
        if prefix[:1].isupper():
            out = [w[:1].upper() + w[1:] for w in out]
        return out

    def learn(self, word: str) -> None:
        w = word.lower().strip()
        if len(w) < 2 or not w.replace("-", "").isalpha():
            return
        with self._lock:
            self.user[w] = self.user.get(w, 0) + 1
            if w not in self.freq and self.user[w] == 1:
                bisect.insort(self.sorted_words, w)
        try:
            with open(self.user_path, "w", encoding="utf-8") as f:
                json.dump(self.user, f, ensure_ascii=False)
        except OSError:
            pass
