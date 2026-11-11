"""Linearise Acadza HTML + MathML into readable plain text (for prompts and checks)."""
import html, re
from html.parser import HTMLParser

class _P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = ["root", {}, []]
        self.stack = [self.root]
    def handle_starttag(self, tag, attrs):
        node = [tag, dict(attrs), []]
        self.stack[-1][2].append(node)
        if tag not in ("br", "img", "hr", "mspace", "input"):
            self.stack.append(node)
        elif tag == "img":
            pass
    def handle_startendtag(self, tag, attrs):
        self.stack[-1][2].append([tag, dict(attrs), []])
    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
    def handle_data(self, data):
        self.stack[-1][2].append(data)

def _r(n):
    if isinstance(n, str):
        return n
    tag, attrs, ch = n
    kids = [c for c in ch if not (isinstance(c, str) and not c.strip())] if tag.startswith("m") else ch
    t = lambda c: _r(c)
    if tag == "mfrac" and len(kids) >= 2:
        return f"({t(kids[0])})/({t(kids[1])})"
    if tag == "msup" and len(kids) >= 2:
        return f"{t(kids[0])}^({t(kids[1])})"
    if tag == "msub" and len(kids) >= 2:
        return f"{t(kids[0])}_{t(kids[1])}"
    if tag == "msubsup" and len(kids) >= 3:
        return f"{t(kids[0])}_{t(kids[1])}^({t(kids[2])})"
    if tag == "msqrt":
        return "sqrt(" + "".join(t(c) for c in kids) + ")"
    if tag == "mroot" and len(kids) >= 2:
        return f"root{t(kids[1])}({t(kids[0])})"
    if tag in ("munder", "mover", "munderover"):
        return "".join(t(c) for c in kids)
    if tag == "br":
        return "\n"
    if tag == "img":
        return f"[IMG {attrs.get('src','')}]"
    if tag == "math":
        return " " + "".join(t(c) for c in kids) + " "
    s = "".join(t(c) for c in kids)
    if tag in ("p", "div", "h1", "h2", "h3", "h4", "li", "tr"):
        return s + "\n"
    if tag in ("td", "th"):
        return s + " | "
    return s

def to_text(h):
    if not h:
        return ""
    p = _P()
    p.feed(h)
    s = _r(p.root)
    s = s.replace("\u00a0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()
