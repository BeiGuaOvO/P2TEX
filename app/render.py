import re
import os

_FONTSET = os.environ.get("CTEX_FONTSET", "").strip()
PREAMBLE = (
    r"\documentclass[UTF8,a4paper,11pt%s]{ctexart}" % (
        ("," + _FONTSET) if _FONTSET else "")
    + "\n" + r"""
\usepackage[margin=2cm]{geometry}
\usepackage{amsmath,amssymb,bm}
\usepackage[version=4]{mhchem}
\usepackage{enumitem}
\usepackage{graphicx}
\usepackage{xcolor}
\setlength{\parindent}{0pt}
\setlist{nosep, leftmargin=2.2em, topsep=0.3em}
\newcommand{\fillblank}[1]{\underline{\hspace{#1}}}
\newcommand{\answerspace}[1][8]{\par\vspace*{#1\baselineskip}}
"""
)
BLANK_CMD = re.compile(r'\\blank\{([\d.]+)\}')
UNDERSCORES = re.compile(r'_{3,}')
UNDERLINE_HSPACE = re.compile(r'\\underline\{\\hspace\{([\d.]+(?:em|ex|cm|mm|pt))\}\}')
OPT_LABEL = re.compile(r'^\s*[（(]?\s*[A-DＡ-Ｄ]\s*[)）.．、:：]\s*')


def to_fillblank(s: str) -> str:
    """把各种填空写法统一成 \fillblank{...}"""
    s = str(s or "")
    # 已经是 \underline{\hspace{6em}} 的，规范化
    s = UNDERLINE_HSPACE.sub(lambda m: r'\fillblank{%s}' % m.group(1), s)
    # 模型输出的显式标记 \blank{4}
    s = BLANK_CMD.sub(lambda m: r'\fillblank{%sem}' % m.group(1), s)
    # 兜底：连续下划线，按长度估算宽度
    s = UNDERSCORES.sub(
        lambda m: r'\fillblank{%dem}' % min(10, max(3, len(m.group(0)) // 2)), s)
    return s


def strip_opt_label(s: str) -> str:
    """去掉选项自带的 A. / （B） 之类前缀，避免和 enumerate 的标签重复"""
    return OPT_LABEL.sub('', str(s or ""), count=1).strip()
def answer_lines(q: dict) -> int:
    """解答题需要的空白行数。"""
    if q.get("options"):
        return 0                                   # 选择题不需要空白
    n = q.get("answer_lines")
    if isinstance(n, int) and 4 <= n <= 40:
        return n
    subs = len(q.get("sub_questions") or [])
    return min(26, 8 + 5 * max(0, subs - 1))       # 兜底：8 行起，每多一问 +5


def render_question(q: dict) -> str:
    out = [r"\item " + to_fillblank(q.get("stem_latex")).strip()]

    for s in q.get("sub_questions") or []:
        lab = str(s.get("label") or "").strip()
        body = to_fillblank(s.get("latex")).strip()
        if lab and body.startswith(lab):
            body = body[len(lab):].strip()
        out.append(r"\par\noindent\hangindent=2em " + ((lab + " ") if lab else "") + body)

    opts = q.get("options") or []
    if opts:
        out.append(r"\begin{enumerate}[label=\Alph*.]")
        for o in opts:
            out.append(r"  \item " + to_fillblank(strip_opt_label(o.get("latex"))))
        out.append(r"\end{enumerate}")

    n = answer_lines(q)
    if n:
        out.append(r"\answerspace[%d]" % n)

    for u in q.get("uncertain") or []:
        out.append("% TODO " + str(u).replace("\n", " "))

    return "\n".join(out)


def render_document(questions: list, title: str = "错题本",
                    author: str = "", date: str = "") -> str:
    head = [PREAMBLE, r"\title{%s}" % title]
    if author:
        head.append(r"\author{%s}" % author)
    head.append(r"\date{%s}" % date)
    head += [
        r"\begin{document}", r"\maketitle", "",
        r"\begin{enumerate}[label=\textbf{\arabic*.},",
        r"  leftmargin=2.8em, itemsep=1.4em, topsep=0.6em]", "",
    ]
    body = [render_question(q) for q in questions]
    tail = [r"\end{enumerate}", r"\end{document}"]
    return "\n".join(head) + "\n\n".join(body) + "\n" + "\n".join(tail)