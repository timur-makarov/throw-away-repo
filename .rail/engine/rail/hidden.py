"""Text a person couldn't see must not reach an agent: HTML comments are taken out of what comes in from GitHub.

GitHub hides `<!-- ... -->` when it renders an issue or a comment, so the person who labels an issue reads the page
without it, while the raw body would carry it into a ticket. A comment inside a fenced code block or an inline code
span is shown as text there, and stays.

Telling the two apart means reading Markdown the way GitHub does, and a reader that disagrees with GitHub in the
wrong direction would keep hidden text. So this one is strict wherever the two could disagree: a comment is kept only
in a fenced block that opens at the start of a line, or in a code span that opens and closes on one plain line.
Everywhere else it goes, and from the first line where the structure is in doubt (a fence inside a list or a quote,
a fence inside raw HTML) every comment goes to the end of the text. Where a comment opens as raw HTML and its `-->`
may not close it for the browser (it opens in a list item, a quote or an HTML block that ends first), the rest of
the text goes with it: an unclosed comment hides everything after it.
"""

import re

# Indentation and the markers of the blocks a line sits in: quotes and list items.
PREFIX = re.compile(r"(?:[ \t]*(?:>|[-*+](?=[ \t]|$)|\d{1,9}[.)](?=[ \t]|$)))*[ \t]*")
FENCE = re.compile(r"(`{3,}|~{3,})")
BACKTICK_OPENER = re.compile(r"(`{3,})[^`]*$")
TILDE_OPENER = re.compile(r"(~{3,}).*$")
# An HTML block that ends at a line holding its end marker, not at a blank line.
TO_MARKER = (
    (re.compile(r"<(?:script|pre|style|textarea)(?:[\s>]|$)", re.I), re.compile(r"</(?:script|pre|style|textarea)>", re.I)),
    (re.compile(r"<\?"), re.compile(r"\?>")),
    (re.compile(r"<!\[CDATA\["), re.compile(r"\]\]>")),
    (re.compile(r"<![A-Za-z]"), re.compile(r">")),
)
HTML_START = re.compile(r"<[A-Za-z/?!]")
BLANK = "blank"


def strip_hidden(text):
    """(the text without the HTML comments a reader of the rendered page can't see, how many were removed)."""
    out, removed, pos, n = [], 0, 0, len(text)
    fence = None      # (the fence's character, its length) while a fenced code block is open
    html = None       # inside an HTML block: BLANK when a blank line ends it, else the pattern of its end marker
    html_top = False  # that block started at the start of a line, in no list item or quote
    doubt = False     # GitHub may read the structure differently from here on: nothing is kept as code any more

    def line_at(p):
        end = text.find("\n", p)
        end = n if end < 0 else end + 1
        return end, text[p:end].rstrip("\r\n")

    def block_end(p):
        """Where the HTML block that holds position p ends: after the line that ends it."""
        while p < n:
            end, bare = line_at(p)
            if html == BLANK and not bare[PREFIX.match(bare).end():]:
                return p
            if html != BLANK and html.search(bare):
                return end
            p = end
        return n

    def strict(p, end, limit):
        """Take every comment out of text[p:end], one line or the rest of one. A comment that doesn't close on the
        line is followed to its `-->` when that comes before `limit`; past it, or with none, the rest of the text
        goes: the browser's comment may not end where this one seems to. Returns where to go on, or None at the end
        of the text."""
        nonlocal removed
        while True:
            start = text.find("<!--", p, end)
            if start < 0:
                out.append(text[p:end])
                return end
            out.append(text[p:start])
            removed += 1
            close = text.find("-->", start + 2)
            if close < 0 or close + 3 > max(limit, end):
                return None
            p = close + 3
            if p > end:
                # The comment ran past this line: what follows its `-->` on that line is raw HTML too.
                end = line_at(p)[0]

    def inline(p, end):
        """A line of ordinary text. A code span that opens and closes on it is kept as it is, comments and all."""
        nonlocal removed, doubt
        line_end = p + len(text[p:end].rstrip("\r\n"))
        plain = not re.search(r"[|$]", text[p:line_end])  # a table cell or maths may cut a span where GitHub reads it
        i = p
        while i < line_end:
            c = text[i]
            if c == "\\" and i + 1 < line_end:
                i += 2
            elif c == "`":
                run = re.compile(r"`+").match(text, i).end() - i
                close = next((m for m in re.finditer(r"`+", text[i + run:line_end]) if len(m.group()) == run), None)
                if close and plain and not doubt:
                    i += run + close.end()
                else:
                    i += run
            elif text.startswith("<!--", i):
                out.append(text[p:i])
                removed += 1
                close = text.find("-->", i + 2)
                if close < 0:
                    return None
                if close + 3 > line_end:
                    # It may be a comment that spans lines, or text GitHub shows: what follows is in doubt either way.
                    doubt = True
                    return strict(close + 3, line_at(close + 3)[0], close + 3)
                p = i = close + 3
            elif c == "<" and i + 1 < line_end and not text[i + 1].isspace():
                close = text.find(">", i + 1, line_end)
                if close < 0:
                    # A tag may go on over the next lines, with a backtick in an attribute: no span is kept until
                    # the paragraph ends.
                    out.append(text[p:i])
                    return strict(i, end, i) if set_html(BLANK, False) else None
                i = i + 1 if "<!--" in text[i:close] else close + 1
            else:
                i += 1
        out.append(text[p:end])
        return end

    def set_html(kind, top):
        nonlocal html, html_top
        html, html_top = kind, top
        return True

    while pos is not None and pos < n:
        end, bare = line_at(pos)
        if fence:
            out.append(text[pos:end])
            closer = re.fullmatch(r" {0,3}(" + re.escape(fence[0]) + r"{" + str(fence[1]) + r",})[ \t]*", bare)
            if closer:
                fence = None
            pos = end
            continue
        prefix = PREFIX.match(bare).group(0)
        inner = bare[len(prefix):]
        fence_like = FENCE.match(inner)
        if html:
            if fence_like:
                doubt = True  # GitHub may have left the HTML block already and be opening a code block here
            if html == BLANK and not inner:
                html = None
                out.append(text[pos:end])
                pos = end
                continue
            last = html != BLANK and html.search(bare)
            pos = strict(pos, end, block_end(pos) if html_top else end)
            if last:
                html = None
            continue
        if fence_like:
            opener = None if prefix or doubt else BACKTICK_OPENER.fullmatch(inner) or TILDE_OPENER.fullmatch(inner)
            if opener:
                fence = (opener.group(1)[0], len(opener.group(1)))
                out.append(text[pos:end])
                pos = end
                continue
            doubt = True  # a fence in a list item or a quote: where it closes depends on what is around it
        if inner.startswith("<!--"):
            # A comment that starts its line is an HTML block of its own, which ends on the line that holds `-->`.
            start = pos + len(prefix)
            close = text.find("-->", start + 2)
            if close >= 0 and close + 3 <= pos + len(bare):
                pos = strict(pos, end, end)  # the whole line is raw HTML: a comment after this one must close on it
            elif close >= 0 and inside(text, pos, close, prefix):
                out.append(text[pos:start])
                removed += 1
                pos = strict(close + 3, line_at(close + 3)[0], close + 3)
            else:
                out.append(text[pos:start])
                removed += 1
                pos = None
            continue
        if HTML_START.match(inner):
            kind = next((to for begins, to in TO_MARKER if begins.match(inner)), BLANK)
            set_html(kind, not prefix)
            continue  # the line is read again, as the block's first
        pos = inline(pos, end)
    return "".join(out), removed


def inside(text, pos, close, prefix):
    """Whether a comment that opens on the line at `pos` stays in the block it opened in up to its `-->` at `close`.
    At the start of a line it is in no block. Indented by spaces alone it may sit in a list item, and stays in it
    while every line up to the closing one is indented as far. Behind a list or quote marker it must close on its
    own line: nothing shows here where that block ends."""
    if not prefix:
        return True
    if prefix.strip(" "):
        return False
    lines = text[pos:text.find("\n", close) if "\n" in text[close:] else len(text)].split("\n")[1:]
    return all(not line.strip() or line.startswith(prefix) for line in lines)
