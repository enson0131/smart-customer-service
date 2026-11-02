import math
import re
from collections import Counter
from pathlib import Path


def tokens(text):
    result = []
    for word in re.findall(r"[\u3400-\u9fff]+|[a-z0-9]+", text.lower()):
        if word.isascii() or len(word) == 1:
            result.append(word)
        else:
            result.extend(word[i:i + 2] for i in range(len(word) - 1))
    return result


class Knowledge:
    def __init__(self, directory):
        self.chunks = []
        for path in sorted(Path(directory).rglob("*")):
            if path.suffix.lower() not in {".txt", ".md"}:
                continue
            title = path.stem
            for part in re.split(r"\n\s*\n|(?=^#{1,6} )", path.read_text().strip(), flags=re.M):
                if part.startswith("#"):
                    heading, _, part = part.partition("\n")
                    title = heading.strip("# ")
                if part.strip():
                    source = {"title": f"{path.stem} · {title}", "excerpt": part.strip()}
                    self.chunks.append((source, Counter(tokens(title + " " + part))))
        self.df = Counter()
        for _, counts in self.chunks:
            self.df.update(counts.keys())
        self.avg = sum(c.total() for _, c in self.chunks) / max(len(self.chunks), 1)

    def search(self, query):
        terms = set(tokens(query))
        ranked = []
        for source, counts in self.chunks:
            matches = terms & counts.keys()
            if not matches or len(matches) / max(len(terms), 1) < 0.22:
                continue
            score = 0
            for t in matches:
                idf = math.log1p((len(self.chunks) - self.df[t] + .5) / (self.df[t] + .5))
                score += idf * counts[t] * 2.2 / (counts[t] + 1.2 * (.25 + .75 * counts.total() / self.avg))
            ranked.append((score, source))
        ranked.sort(key=lambda item: -item[0])
        return [source for score, source in ranked[:2] if score >= ranked[0][0] * .65]
