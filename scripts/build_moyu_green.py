#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飞书文档 XML → 微信公众号「摸鱼绿（moyu-green）」排版 HTML（纯 <section> 片段）。

这是「摸鱼绿」的**参考实现**：输出的字号 / 内边距 / 组件组合，与
references/theme-moyu-green.md 开头的「⭐ 本机定版规范」逐条对齐
（正文 16.5px、卡片内边距 16px、正文容器不加左右 padding、速览卡 16/15px ……）。

输入：飞书文档导出的 XML（用 lark-cli 抓，见 README「生成器」一节）：
    lark-cli docs +fetch --doc "<文档URL>" --as user --doc-format xml --detail full > doc.xml
输出：`<段落片段>.html`（可直接粘进公众号编辑器）+ 同名 `.title.txt`（标题）。

依赖：python3 + lxml（`pip3 install lxml`）。Chrome 仅在需要肉眼验收 390px 时使用。

用法:
    python3 scripts/build_moyu_green.py <doc.xml> <out.html>

每篇文章要改的 5 处（都在本文件内，搜注释即可）：
    1. cover()           封面文案（顶栏标签、删除线小字、主标题两行、副标题关键词条、底栏标签）
    2. INTRO / DATE_LINE 引言句 + 日期行
    3. CHAPTER_META      11 个章节徽标（编号 / 英文名 / PART 或 APPENDIX）
    4. END_BLOCK / SIGN_BLOCK / FOOTER_CTA  结尾三块（含 `{{作者名}}` 占位）
    5. summary_card() 等卡片里的固定小标题（如「🎯 全文速览」）

不在脚本里做的事（交付前人工过一遍）：
    - 校验：python3 scripts/validate_gzh_html.py <out.html> 必须 0 ERROR / 0 WARNING
    - 390px 手机宽度目检：表格数字不断行、卡片不溢出
"""
import re
import sys
from lxml import etree

# ---------------- 主题设计变量（theme-moyu-green） ----------------
EM = "#059669"        # 主色 emerald-600
EM2 = "#10B981"       # 辅色 emerald-500
EM_UNDER = "#A7F3D0"  # 正文关键词下划线
EM_PALE = "#ECFDF5"   # 极浅绿背景
EM_BG = "#F0FDF4"     # 浅绿背景
EM_BORDER = "#BBF7D0"  # 浅绿边框
YELLOW = "#FDE68A"    # 黄色高亮
TITLE_C = "#111827"   # 标题色
BODY = "#374151"      # 正文色
SECOND = "#4B5563"    # 次要文字
NOTE = "#6B7280"      # 注释
MUTED = "#9CA3AF"     # 辅助文字
LINE = "#E5E7EB"      # 浅边框
GRAY_LINE = "#D1D5DB"  # 分隔线
LIGHT = "#F9FAFB"     # 极浅灰
WARN_TXT = "rgb(255,76,0)"
WARN_GRAY = "rgb(136,136,136)"

BLOCK_TAGS = {"p", "ul", "ol", "blockquote", "table", "h2", "h3", "callout", "hr", "title"}


# ---------------- 文本 ----------------
def norm(s):
    s = s.replace("\r", "").replace("\n", "")
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def frag(text, style=""):
    if not text:
        return ""
    t = esc(text)
    if style:
        return f'<span style="{style}"><span leaf="">{t}</span></span>'
    return f'<span leaf="">{t}</span>'


def is_hl(ch):
    bg = (ch.attrib.get("background-color") or "").replace(" ", "")
    return ("255,246,122" in bg) or ("255,235," in bg) or ("yellow" in bg)


def inline_segments(el):
    """收集行内片段 [(kind, text)]，kind: text/bold/em/hl/br。"""
    segs = []

    def walk(node):
        if node.text:
            segs.append(("text", norm(node.text)))
        for ch in node:
            if ch.tag in BLOCK_TAGS:
                if ch.tail:
                    segs.append(("text", norm(ch.tail)))
                continue
            if ch.tag in ("b", "strong"):
                segs.append(("bold", norm("".join(ch.itertext()))))
            elif ch.tag in ("em", "i"):
                segs.append(("em", norm("".join(ch.itertext()))))
            elif ch.tag == "br":
                segs.append(("br", ""))
            elif ch.tag == "span":
                segs.append(("hl" if is_hl(ch) else "text", norm("".join(ch.itertext()))))
            else:
                segs.append(("text", norm("".join(ch.itertext()))))
            if ch.tail:
                segs.append(("text", norm(ch.tail)))

    walk(el)
    return clean_segments(segs)


def clean_segments(segs):
    merged = []
    for kind, text in segs:
        if kind == "br":
            merged.append((kind, ""))
        elif merged and merged[-1][0] == "text" and kind == "text":
            merged[-1] = ("text", merged[-1][1] + text)
        else:
            merged.append((kind, text))
    out = []
    for i, (kind, text) in enumerate(merged):
        if kind != "br":
            text = re.sub(r" +", " ", text)
            if i == 0:
                text = text.lstrip()
            if i == len(merged) - 1:
                text = text.rstrip()
        out.append((kind, text))
    return [s for s in out if s[0] == "br" or s[1].strip()]


NUM_RE = re.compile(r"[0-9０-９]|亿|万亿|%|倍|GW|美元")

# 锚点层：全文 ≤5 处绿色加粗（仅首次出现生效）
GREEN_ANCHORS = ["8,137 亿美元", "2.23–2.78 万亿美元", "4,450–5,550 亿美元", "130–160 亿美元"]
_anchor_used = set()


def pick_underlines(segs):
    """每段挑 1~2 个加粗片段改成绿色下划线（6e）。"""
    total = sum(len(t) for _, t in segs)
    cand = []
    for i, (kind, text) in enumerate(segs):
        if kind != "bold":
            continue
        t = text.strip()
        if len(t) < 3 or len(t) > 26 or t[-1] in "：:，,；;、":
            continue
        # 整段几乎都是加粗时不要划线（划线会变成整段划重点）
        if total and len(t) / total > 0.6:
            continue
        score = 3 if NUM_RE.search(t) else 0
        if 4 <= len(t) <= 18:
            score += 1
        cand.append((score, i))
    cand.sort(key=lambda x: -x[0])
    if not cand:
        return set()
    k = 2 if len(segs) > 4 and len(cand) > 2 else 1
    chosen = set(i for _, i in cand[:k])
    if len(chosen) * 3 >= len(segs):
        chosen = set(list(chosen)[:1])
    return chosen


def render_inline(segs, mode="para"):
    under = pick_underlines(segs) if mode == "para" else set()
    out = []
    for i, (kind, text) in enumerate(segs):
        if kind == "br":
            out.append("<br/>")
        elif kind == "bold":
            t = text.strip()
            if t in GREEN_ANCHORS and t not in _anchor_used:
                _anchor_used.add(t)
                out.append(f'<strong style="color:{EM};"><span leaf="">{esc(text)}</span></strong>')
            elif i in under:
                out.append(f'<span style="border-bottom:2px solid {EM_UNDER};font-weight:600;">'
                           f'<span leaf="">{esc(text)}</span></span>')
            else:
                out.append(f'<strong style="color:{TITLE_C};"><span leaf="">{esc(text)}</span></strong>')
        elif kind == "em":
            out.append(f'<span style="color:{NOTE};font-style:italic;">'
                       f'<span leaf="">{esc(text)}</span></span>')
        elif kind == "hl":
            out.append(f'<span style="background:linear-gradient(120deg,{YELLOW} 0%,'
                       f'rgba(255,255,255,0) 100%);padding:0 4px;border-radius:2px;'
                       f'font-weight:600;color:{TITLE_C};"><span leaf="">{esc(text)}</span></span>')
        else:
            out.append(frag(text))
    return "".join(out)


def plain(el):
    return norm("".join(el.itertext())).strip()


# ---------------- 基础排版件 ----------------
def pad(inner, top=0, bottom=0):
    return (f'<section style="padding:0;margin-top:{top}px;'
            f'margin-bottom:{bottom}px;">{inner}</section>')


def p_raw(inner, fs=16, color=BODY, mb=18, justify=True):
    ta = "text-align:justify;" if justify else ""
    return (f'<p style="margin:0 0 {mb}px;font-size:{fs}px;line-height:1.8;'
            f'{ta}color:{color};">{inner}</p>')



def p_para(el, fs=16, mb=18, mode="para", justify=True):
    return p_raw(render_inline(inline_segments(el), mode), fs=fs, mb=mb,
                 justify=justify)



def p_text(text, fs=16, mb=18, color=BODY, justify=True):
    return p_raw(frag(text), fs=fs, mb=mb, color=color, justify=justify)



def p_note(text):
    return (f'<p style="margin:0 0 20px;font-size:13.5px;line-height:1.85;color:{MUTED};'
            f'text-align:justify;"><span style="font-style:italic;">'
            f'<span leaf="">{esc(text)}</span></span></p>')



def bullet(items, fs=15.5, indent=0, mb=12, dot=EM):
    """绿色圆点要点行（11a 圆点的展开写法，长句更稳）。"""
    out = []
    for inner, nested in items:
        pad_css = f"padding-left:{indent}px;" if indent else ""
        out.append(
            f'<section style="display:flex;align-items:flex-start;{pad_css}margin-bottom:{mb}px;">'
            f'<span style="display:inline-block;width:7px;height:7px;background:{dot};'
            f'border-radius:50%;margin:10px 9px 0 0;flex-shrink:0;">'
            f'<span leaf=""><br></span></span>'
            f'<p style="font-size:{fs}px;color:{BODY};margin:0;line-height:1.8;flex:1;'
            f'text-align:justify;">{inner}</p></section>')
        if nested:
            out.append(nested)
    return "".join(out)



def ordered(items, fs=16, mb=14):
    """11g ordered-list：绿色圆标数字。"""
    out = []
    for i, (inner, nested) in enumerate(items, 1):
        out.append(
            f'<section style="display:flex;align-items:flex-start;gap:10px;margin-bottom:{mb}px;">'
            f'<span style="display:inline-flex;align-items:center;justify-content:center;'
            f'width:24px;height:24px;background:{EM};color:#fff;font-size:12.5px;'
            f'font-weight:700;border-radius:50%;flex-shrink:0;margin-top:4px;">'
            f'<span leaf="">{i}</span></span>'
            f'<section style="flex:1;">'
            f'<p style="font-size:{fs}px;color:{BODY};margin:0;line-height:1.8;'
            f'text-align:justify;">{inner}</p>{nested}</section></section>')
    return "".join(out)



def chapter_title(no, cn, en, first=False, label="PART", last=False):
    """组件 4 chapter-title。"""
    mt = "20px" if first else "52px"
    no_fs = 26 if no == "///" else 30
    return (
        f'<section style="margin-top:{mt};margin-bottom:24px;padding:0;">'
        f'<section style="display:flex;align-items:center;gap:16px;margin-bottom:24px;">'
        f'<section style="text-align:center;flex-shrink:0;">'
        f'<p style="margin:0;font-size:{no_fs}px;font-weight:900;color:{EM};line-height:1;'
        f'letter-spacing:-2px;"><span leaf="">{no}</span></p>'
        f'<p style="margin:0;font-size:11.5px;font-weight:700;color:{GRAY_LINE};'
        f'letter-spacing:2px;"><span leaf="">{label}</span></p>'
        f'</section>'
        f'<span style="width:1px;height:40px;background:{LINE};flex-shrink:0;">'
        f'<span leaf=""><br></span></span>'
        f'<section style="flex:1;min-width:0;">'
        f'<p style="margin:0 0 2px;font-size:19px;font-weight:900;color:{TITLE_C};'
        f'letter-spacing:0.3px;line-height:1.4;"><span leaf="">{esc(cn)}</span></p>'
        f'<p style="margin:0;font-size:12px;font-weight:600;color:{MUTED};'
        f'letter-spacing:1.5px;"><span leaf="">{en}</span></p>'
        f'</section></section></section>')



def subhead(text, mt=32):
    """组件 9c subtitle-highlight：黄色下划线小节标题。"""
    return (f'<p style="font-size:17px;font-weight:900;color:{TITLE_C};margin:{mt}px 0 18px;'
            f'line-height:1.6;"><span style="background:linear-gradient(180deg,'
            f'transparent 65%,{YELLOW} 65%);padding:0 4px;">'
            f'<span leaf="">{esc(text)}</span></span></p>')



def quote_box(blocks):
    """组件 9a quote-box：灰色虚线引用框（本主题特征）。"""
    return (f'<section style="background:{LIGHT};border:1px dashed {GRAY_LINE};'
            f'border-radius:8px;padding:14px 16px;margin-bottom:26px;text-align:justify;">'
            f'{blocks}</section>')



def green_info(blocks, label=""):
    """组件 10d green-info：绿色信息框。"""
    head = ""
    if label:
        head = (f'<p style="font-size:12.5px;font-weight:800;color:{EM};letter-spacing:1.5px;'
                f'margin:0 0 12px;"><span leaf="">{label}</span></p>')
    return (f'<section style="background:{EM_BG};padding:16px 16px;border-radius:12px;'
            f'border:1px solid {EM_BORDER};margin-bottom:26px;">{head}{blocks}</section>')



# ---------------- 表格 11f ----------------
def cell_segments(c):
    paras = c.findall("./p")
    if paras:
        segs = []
        for p in paras:
            segs.extend(inline_segments(p))
            segs.append(("text", " "))
        return clean_segments(segs)
    return inline_segments(c)


def text_px(s, fs):
    """估算文字像素宽（中文 1em，数字 0.56em，空格/标点更窄）。"""
    w = 0.0
    for ch in s:
        if ch.isdigit():
            w += 0.56 * fs
        elif ch in ".,:;":
            w += 0.30 * fs
        elif ch in " /\u2013\u2014-+\u00d7\u2248\u00f7%":
            w += 0.34 * fs
        elif ord(ch) > 127:
            w += 1.0 * fs
        else:
            w += 0.55 * fs
    return w


def _col_needs(cells, fs, pad_px, avail_cap=86.0):
    """返回 (原子最小宽, 内容最大宽)。原子=短数字/单位，整段不许拆行。"""
    atomic, flex = 0.0, 0.0
    for c in cells:
        t = plain(c)
        if not t:
            continue
        w = text_px(t, fs)
        bold = c.tag == "th" or bool(c.findall(".//b")) or bool(c.findall(".//strong"))
        factor = 1.12 if bold else 1.0
        flex = max(flex, w * factor)
        if w <= fs * 6.2:
            # 单列不越过 24.5% 版心：数字列够一行即可，别把标签列挤成竖条
            atomic = min(max(atomic, w * factor + 2 * pad_px + 4), avail_cap)
    return atomic, flex


def _col_widths(cells_by_col, base, fs, pad_px, avail=350.0):
    """列宽：优先满足原子内容，剩余按源 colgroup 比例分；不挤成竖条。"""
    n = len(cells_by_col)
    needs, flexes = [], []
    for cs in cells_by_col:
        a, f = _col_needs(cs, fs, pad_px, avail * 0.245)
        needs.append(a)
        flexes.append(f)
    w = [max(base[i] * avail, needs[i], fs * 4.4) for i in range(n)]
    total = sum(w)
    if total > avail:
        slack = [max(0.0, w[i] - max(needs[i], fs * 4.4)) for i in range(n)]
        sl = sum(slack)
        if sl > 0:
            for i in range(n):
                w[i] = max(w[i] - (total - avail) * slack[i] / sl,
                           needs[i], fs * 4.4)
        else:
            w = [x * avail / total for x in w]
    elif total < avail:
        weights = [max(flexes[i] - needs[i], 0.0) for i in range(n)]
        sw = sum(weights) or 1.0
        for i in range(n):
            w[i] += (avail - total) * weights[i] / sw
    return [f"{x / avail * 100:.1f}%" for x in w]


def table_html(el):
    cols = el.findall("./colgroup/col")
    widths = [c.attrib.get("width") for c in cols]
    thead = el.find("./thead")
    tbody = el.find("./tbody")
    head_rows = thead.findall("./tr") if thead is not None else []
    body_rows = tbody.findall("./tr") if tbody is not None else []

    ncol = 0
    if head_rows:
        ncol = len(head_rows[0].findall("./th")) or len(head_rows[0].findall("./td"))
    elif body_rows:
        ncol = len(body_rows[0].findall("./td"))

    colmax = [0] * ncol
    for tr in head_rows + body_rows:
        cells = tr.findall("./th") or tr.findall("./td")
        for i, c in enumerate(cells):
            if i < ncol:
                colmax[i] = max(colmax[i], len(plain(c)))
    align = ["left" if colmax[i] > 12 else "center" for i in range(ncol)]
    if ncol:
        align[0] = "left"

    if ncol >= 5:
        fs, padc, hfs = 13, "9px 2px", 12.5
    elif ncol == 4:
        fs, padc, hfs = 14, "9px 5px", 13
    else:
        fs, padc, hfs = 14.5, "9px 9px", 13.5

    # ---- 列宽：源 colgroup 比例 + 原子内容下限 ----
    pad_px = float(padc.split()[1].replace("px", ""))
    cells_by_col = []
    for i in range(ncol):
        col_cells = []
        for tr in head_rows + body_rows:
            cs = tr.findall("./th") or tr.findall("./td")
            if i < len(cs):
                col_cells.append(cs[i])
        cells_by_col.append(col_cells)

    base = None
    try:
        nums = [float(x) for x in widths]
        tot = sum(nums)
        if len(nums) == ncol and tot:
            base = [n / tot for n in nums]
    except Exception:
        base = None
    if base is None:
        base = [1.0 / ncol] * ncol

    pct = _col_widths(cells_by_col, base, fs, pad_px)

    out = [f'<section style="margin:0 0 26px;overflow-x:auto;">',
           f'<table style="width:100%;border-collapse:collapse;font-size:{fs}px;'
           f'table-layout:fixed;">']
    if head_rows:
        out.append("<thead>")
        for tr in head_rows:
            cells = tr.findall("./th") or tr.findall("./td")
            out.append("<tr>")
            for i, c in enumerate(cells):
                wd = f'width:{pct[i]};' if i < len(pct) else ""
                a = align[i] if i < ncol else "left"
                out.append(
                    f'<th style="background:{EM};color:#fff;font-weight:700;{wd}'
                    f'padding:{padc};text-align:{a};line-height:1.45;font-size:{hfs}px;'
                    f'vertical-align:middle;">{render_inline(cell_segments(c), "cell")}</th>')
            out.append("</tr>")
        out.append("</thead>")
    if body_rows:
        out.append("<tbody>")
        for ri, tr in enumerate(body_rows):
            cells = tr.findall("./td")
            hot = any(c.attrib.get("background-color") for c in cells)
            if hot:
                bg = f"background:{EM_PALE};"
            elif ri % 2 == 1:
                bg = f"background:{LIGHT};"
            else:
                bg = ""
            out.append("<tr>")
            for i, c in enumerate(cells):
                wd = f'width:{pct[i]};' if i < len(pct) else ""
                a = align[i] if i < ncol else "left"
                out.append(
                    f'<td style="{wd}{bg}padding:{padc};border-bottom:1px solid {LINE};'
                    f'color:{BODY};text-align:{a};line-height:1.6;vertical-align:top;">'
                    f'{render_inline(cell_segments(c), "cell")}</td>')
            out.append("</tr>")
        out.append("</tbody>")
    out.append("</table></section>")
    return "".join(out)



# ---------------- 列表 / 容器内部 ----------------
def list_items(el, mode="para", sub_fs=14.5):
    items = []
    for li in el.findall("./li"):
        inner = render_inline(inline_segments(li), mode)
        nested = []
        for ch in li:
            if ch.tag == "ul":
                nested.append(bullet(list_items(ch, mode, sub_fs), fs=sub_fs, mb=9,
                                     dot="#6EE7B7"))
            elif ch.tag == "ol":
                nested.append(ordered(list_items(ch, mode, sub_fs), fs=sub_fs, mb=9))
            elif ch.tag == "blockquote":
                nested.append(quote_box(render_children(ch, fs=14, mark=False)))
        items.append((inner, "".join(nested)))
    return items


def render_children(el, fs=15, mark=True, justify=True):
    parts = []
    for ch in el:
        if ch.tag == "p":
            if plain(ch):
                parts.append(p_para(ch, fs=fs, mb=10,
                                    mode="para" if mark else "cell",
                                    justify=justify))
        elif ch.tag == "ul":
            m = "para" if mark else "cell"
            parts.append(f'<section style="margin:0 0 10px;">'
                         f'{bullet(list_items(ch, m), fs=fs, mb=8)}</section>')
        elif ch.tag == "ol":
            m = "para" if mark else "cell"
            parts.append(f'<section style="margin:0 0 10px;">'
                         f'{ordered(list_items(ch, m), fs=fs, mb=8)}</section>')
        elif ch.tag == "blockquote":
            parts.append(quote_box(render_children(ch, fs=fs - 0.5, mark=False)))
    return "".join(parts)



# ---------------- 判断 ----------------
def is_subhead_p(el):
    segs = inline_segments(el)
    if not segs:
        return False
    bold = "".join(t for k, t in segs if k == "bold")
    other = "".join(t for k, t in segs if k in ("text", "em", "hl")).strip()
    if not bold or len(bold) > 34:
        return False
    if other not in ("", "：", ":", "——", "。"):
        return False
    if bold.endswith(("？", "：", ":", "——")):
        return True
    return len(bold) <= 20


def is_note_p(el):
    segs = inline_segments(el)
    return bool(segs) and all(k == "em" for k, _ in segs)


# ---------------- 前置区：封面 + 目录 + 引言 ----------------
def cover():
    """组件 2 cover-breaking（无右侧图片版）。"""
    return (
        '<section style="margin:0 0 30px;background:#fff;'
        f'border:1.5px solid rgba(5,150,105,0.15);border-radius:20px;overflow:hidden;'
        'box-shadow:0 4px 20px rgba(0,0,0,0.06);width:100%;">'
        '<section style="padding:26px 20px 22px;">'
        # 顶栏
        '<section style="display:flex;align-items:center;gap:8px;margin-bottom:26px;">'
        f'<span style="width:7px;height:7px;background:{EM};border-radius:50%;">'
        '<span leaf=""><br></span></span>'
        f'<span style="font-size:12px;font-weight:700;letter-spacing:2.5px;color:{EM};">'
        '<span leaf="">AI 算力 · 回本账</span></span>'
        '<section style="flex:1;height:1px;overflow:hidden;background:linear-gradient(to right,'
        'rgba(5,150,105,0.12),transparent);"><span leaf=""><br></span></section>'
        f'<span style="font-size:12px;color:{GRAY_LINE};font-weight:600;">'
        '<span leaf="">2026.10</span></span>'
        '</section>'
        # 标题区
        '<section>'
        f'<p style="font-size:16px;color:{GRAY_LINE};margin:0 0 8px;text-decoration:line-through;'
        'letter-spacing:0.5px;"><span leaf="">1 年回本 = 没有泡沫</span></p>'
        f'<p style="font-size:26px;font-weight:900;color:{TITLE_C};margin:0;line-height:1.2;'
        f'letter-spacing:-1px;"><span leaf="">AI 是不是泡沫，</span>'
        f'<span style="color:{EM};"><span leaf="">取决于</span></span></p>'
        f'<p style="font-size:26px;font-weight:900;color:{EM};margin:0 0 16px;line-height:1.2;'
        'letter-spacing:-1px;"><span leaf="">你算哪一本账</span></p>'
        f'<section style="width:48px;height:3px;background:linear-gradient(to right,{EM},{EM2});'
        'border-radius:2px;margin-bottom:14px;"><span leaf=""><br></span></section>'
        f'<p style="font-size:15px;color:{MUTED};margin:0;line-height:1.7;letter-spacing:0.3px;">'
        '<span leaf="">单批回本 · 稳态回本 · 8,137 亿 · 2.23 万亿</span></p>'
        '</section></section>'
        # 底条
        f'<section style="background:linear-gradient(135deg,{EM},{EM2});padding:12px 20px;'
        'display:flex;align-items:center;justify-content:space-between;">'
        '<p style="font-size:13px;color:rgba(255,255,255,0.9);margin:0;font-weight:600;'
        'letter-spacing:0.5px;"><span leaf="">AI 资本开支拆解</span></p>'
        '<section style="display:flex;gap:5px;">'
        '<span style="background:rgba(255,255,255,0.2);padding:2px 7px;border-radius:3px;'
        'font-size:11.5px;color:#fff;font-weight:600;"><span leaf="">CAPEX</span></span>'
        '<span style="background:rgba(255,255,255,0.2);padding:2px 7px;border-radius:3px;'
        'font-size:11.5px;color:#fff;font-weight:600;"><span leaf="">ROI</span></span>'
        '</section></section></section>')



TOC_ITEMS = [
    ("PART 01", "先看清这笔钱", "1.5 万亿资本开支"),
    ("PART 02", "单批账", "五步倒推"),
    ("PART 03", "门槛阶梯总表", "三档费用率"),
    ("PART 04", "三个关键变量", "寿命 · 通缩 · 折旧"),
    ("PART 05", "稳态账", "每年 2 万亿+"),
    ("PART 06", "两种账", "单批 vs 稳态"),
    ("PART 07", "需求侧", "1,170 亿美元"),
    ("PART 08", "五个硬指标", "三个风险信号"),
    ("PART ///", "写在最后", "结论：三句话"),
]


def toc():
    """目录：竖排条目（不用横向滚动，粘到公众号后每一节都可见）。"""
    rows = []
    for i, (label, name, sub) in enumerate(TOC_ITEMS):
        first = i == 0
        last = i == len(TOC_ITEMS) - 1
        border = "" if last else 'border-bottom:1px solid #F3F4F6;'
        if first:
            badge = (f'<span style="display:inline-block;background:linear-gradient(135deg,{EM},{EM2});'
                     'color:#fff;font-size:11.5px;font-weight:800;letter-spacing:0.5px;'
                     'padding:3px 8px;border-radius:10px;flex-shrink:0;margin-right:10px;">'
                     f'<span leaf="">{label}</span></span>')
        else:
            badge = (f'<span style="display:inline-block;background:rgba(5,150,105,0.10);'
                     f'color:{EM};font-size:11.5px;font-weight:800;letter-spacing:0.5px;'
                     'padding:3px 8px;border-radius:10px;flex-shrink:0;margin-right:10px;">'
                     f'<span leaf="">{label}</span></span>')
        rows.append(
            f'<section style="display:flex;align-items:center;padding:12px 0;{border}">'
            + badge
            + '<section style="flex:1;min-width:0;">'
            f'<p style="margin:0;font-size:15px;font-weight:800;color:{TITLE_C};'
            'line-height:1.5;">'
            f'<span leaf="">{name}</span></p>'
            f'<p style="margin:0;font-size:12.5px;color:{MUTED};line-height:1.5;">'
            f'<span leaf="">{sub}</span></p></section></section>')
    return (
        '<section style="margin:0 0 30px;">'
        '<section style="display:flex;align-items:center;justify-content:space-between;'
        'margin-bottom:12px;">'
        f'<p style="font-size:12px;color:{MUTED};margin:0;text-transform:uppercase;'
        'letter-spacing:2px;font-weight:600;"><span leaf="">📦 8 Parts + Conclusion</span></p>'
        f'<p style="font-size:12px;color:{MUTED};margin:0;"><span leaf="">共 9 个部分</span></p>'
        '</section>'
        f'<section style="background:#fff;border:1px solid {LINE};border-radius:12px;'
        'padding:2px 16px;box-shadow:0 2px 6px rgba(0,0,0,0.04);">'
        + "".join(rows) + '</section></section>')



INTRO = (
    f'<section style="background:#FFF;border:1px dashed {EM_BORDER};border-radius:8px;'
    'padding:16px 16px;margin-bottom:18px;text-align:center;">'
    f'<p style="font-size:13.5px;color:{MUTED};margin:0 0 8px;line-height:1.5;">'
    '<span leaf="">一句话 · 全文结论</span></p>'
    '<p style="margin:0;line-height:1.75;">'
    f'<span style="font-size:17px;color:{EM};font-weight:bold;border-bottom:3px solid {YELLOW};'
    'padding-bottom:2px;"><span leaf="">AI 是不是泡沫，取决于你算的是「单批回本」'
    '还是「年年投的稳态回本」——两者差一个量级。</span></span></p></section>'
)

DATE_LINE = (
    f'<section style="padding:0;"><p style="text-align:center;font-size:13.5px;'
    f'color:{MUTED};letter-spacing:1px;margin:0 0 26px;">'
    '<span leaf="">2026 年 10 月 21 日 · 极简版</span></p></section>'
)


def summary_card(el):
    """🎯 callout 去掉首段金句 → 全文速览卡。"""
    blocks = []
    for ch in el:
        if ch.tag == "p":
            continue
        if ch.tag in ("ul", "ol"):
            items = list_items(ch, sub_fs=14.5)
            fn = bullet if ch.tag == "ul" else ordered
            blocks.append(f'<section style="margin:0 0 10px;">{fn(items, fs=15.5, mb=10)}</section>')
    return green_info("".join(blocks), "🎯 全文速览")


def formula_card(el):
    """⭐ 速记公式 → green-info 强调卡。"""
    segs = []
    for p in el.findall("./p"):
        segs.extend(inline_segments(p))
    if segs and segs[0][0] == "bold" and segs[0][1].strip() == "速记公式":
        segs = segs[1:]
        if segs and segs[0][0] == "text":
            segs[0] = ("text", segs[0][1].lstrip("：:"))
    return green_info(
        f'<p style="font-size:16.5px;font-weight:800;color:{EM};margin:0;line-height:1.9;">'
        f'{render_inline(segs, "cell")}</p>', "⭐ 速记公式")


def metaphor_card(el):
    """💡 两句账的隐喻 → quote-box。"""
    blocks = []
    for ch in el:
        if ch.tag == "p" and plain(ch):
            blocks.append(p_para(ch, fs=15.5, mb=10))
    return quote_box("".join(blocks))


def check_card(el):
    """🎁 可观察的检验标准 → green-info 卡。"""
    blocks = []
    for ch in el:
        if ch.tag == "p" and plain(ch):
            blocks.append(p_para(ch, fs=16, mb=10))
    return green_info("".join(blocks), "🎁 可观察的检验标准")


# ---------------- 章节编号 ----------------
CHAPTER_META = [
    ("01", "THE MONEY", "PART"),
    ("02", "ONE BATCH", "PART"),
    ("03", "THRESHOLDS", "PART"),
    ("04", "VARIABLES", "PART"),
    ("05", "STEADY STATE", "PART"),
    ("06", "TWO LEDGERS", "PART"),
    ("07", "DEMAND SIDE", "PART"),
    ("08", "SIGNALS", "PART"),
    ("///", "CONCLUSION", "LAST"),
    ("A", "APPENDIX A", "APPENDIX"),
    ("B", "APPENDIX B", "APPENDIX"),
]
CN_PREFIX = re.compile(r"^(?:[一二三四五六七八九十]+、|附[一二三]：)")


def chapter_head(idx, h2text):
    no, en, label = CHAPTER_META[idx]
    title = CN_PREFIX.sub("", h2text).strip()
    return chapter_title(no, title, en, first=(no == "01"), label=label)


# ---------------- 结尾 ----------------
DIVIDER = (f'<section style="padding:0;"><section style="height:1px;'
           f'background:{LINE};margin:8px 0;"><span leaf=""><br></span></section></section>')

END_BLOCK = (
    '<section style="padding:0;">'
    f'<p style="font-size:13.5px;margin:12px 0 26px;text-align:center;color:{EM};'
    'font-weight:700;letter-spacing:3px;border-top:1px solid #F3F4F6;'
    'border-bottom:1px solid #F3F4F6;padding:12px 0;">'
    '<span leaf="">— END —</span></p></section>'
)

SIGN_BLOCK = (
    '<section style="padding:0;">'
    f'<p style="margin:0 0 18px;font-size:16px;line-height:1.85;text-align:justify;">'
    '<span leaf="">我是 </span><strong style="color:' + TITLE_C + ';">'
    '<span leaf="">{{作者名}}</span></strong>'
    '<span leaf="">，{{一句话简介，如：专注于 AI 与算力产业的深度拆解}}。</span></p>'
    '</section>'
)

def _cta_item(emoji, label, color, box_bg="#fff", box_border="#F3F4F6",
              box_shadow="rgba(0,0,0,0.05)"):
    """CTA 单项：40×40 浅底圆角盒子 + emoji + 文字（不用 svg，微信会剥离）。"""
    return (
        f'<section style="text-align:center;color:{color};">'
        f'<section style="width:40px;height:40px;display:flex;align-items:center;'
        f'justify-content:center;margin:0 auto 6px;background:{box_bg};border-radius:12px;'
        f'box-shadow:0 2px 4px {box_shadow};border:1px solid {box_border};">'
        f'<span style="font-size:20px;line-height:1;"><span leaf="">{emoji}</span></span>'
        '</section>'
        f'<span style="font-size:12px;font-weight:600;"><span leaf="">{label}</span></span>'
        '</section>')


FOOTER_CTA = (
    f'<section style="background:radial-gradient(circle at center,{LIGHT} 0%,#FFFFFF 100%);'
    f'border:1px solid {LINE};border-radius:16px;padding:28px 18px;text-align:center;'
    'box-shadow:0 4px 12px rgba(0,0,0,0.03);margin:0 0 24px;">'
    f'<p style="font-size:15px;font-weight:bold;color:{TITLE_C};margin-bottom:20px;'
    'line-height:1.7;"><span leaf="">既然看到这里了，如果觉得有用，'
    '随手点个赞、在看、转发三连吧。</span></p>'
    '<section style="display:flex;justify-content:center;gap:24px;margin-bottom:16px;">'
    + _cta_item("👍", "点赞", SECOND)
    + _cta_item("👀", "在看", SECOND)
    + _cta_item("🔄", "转发", EM, box_bg=EM_PALE, box_border="#A7F3D0",
                box_shadow="rgba(5,150,105,0.15)")
    + '</section>'
    f'<p style="font-size:11.5px;color:{MUTED};letter-spacing:1.5px;margin:0;">'
    '<span leaf="">THANKS FOR READING</span></p></section>'
)


# ---------------- 组装 ----------------
def build(src_xml):
    root = etree.fromstring("<root>" + open(src_xml, encoding="utf-8").read() + "</root>")
    doc_title = plain(root.find("./title"))
    blocks = list(root)

    out = ['<section style="max-width:677px;margin:0 auto;background:#ffffff;'
           "font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB',"
           "'Microsoft YaHei',sans-serif;color:#374151;line-height:1.75;letter-spacing:0.5px;"
           'overflow-x:hidden;">']

    out.append(cover())
    out.append(toc())
    out.append(pad(INTRO))
    out.append(DATE_LINE)

    ch_idx = -1
    for i, el in enumerate(blocks):
        tag = el.tag
        if tag == "title":
            continue
        if i == 1:            # 日期行已手工渲染
            continue
        if i == 2:            # 🎯 callout：首段作引言，其余作速览
            out.append(pad(summary_card(el)))
            continue
        if tag == "h2":
            ch_idx += 1
            if ch_idx < len(CHAPTER_META):
                out.append(chapter_head(ch_idx, plain(el)))
            else:
                out.append(pad(subhead(plain(el))))
            continue
        if tag == "hr":
            out.append(DIVIDER)
            continue
        if tag == "h3":
            out.append(pad(subhead(plain(el))))
            continue
        if tag == "p":
            if not plain(el):
                continue
            if is_note_p(el):
                out.append(pad(p_note(plain(el))))
            elif is_subhead_p(el):
                out.append(pad(subhead(plain(el))))
            else:
                out.append(pad(p_para(el)))
            continue
        if tag == "ul":
            out.append(pad(f'<section style="margin:0 0 12px;">'
                           f'{bullet(list_items(el))}</section>'))
            continue
        if tag == "ol":
            out.append(pad(f'<section style="margin:0 0 12px;">'
                           f'{ordered(list_items(el))}</section>'))
            continue
        if tag == "table":
            out.append(pad(table_html(el)))
            continue
        if tag == "blockquote":
            # 来源类脚注里英文/数字密集，强制两端对齐会把字距撑开，改左对齐
            j = not plain(el).startswith("来源")
            out.append(pad(quote_box(render_children(el, fs=15, mark=False,
                                                     justify=j))))
            continue
        if tag == "callout":
            emoji = el.attrib.get("emoji", "")
            if emoji == "⭐":
                out.append(pad(formula_card(el)))
            elif emoji == "💡":
                out.append(pad(metaphor_card(el)))
            elif emoji == "🎁":
                out.append(pad(check_card(el)))
            else:
                out.append(pad(green_info(render_children(el, fs=15),
                                          (emoji or "📌") + " 提示")))
            continue
        txt = plain(el)
        if txt:
            out.append(pad(p_text(txt)))

    out.append(END_BLOCK)
    out.append(SIGN_BLOCK)
    out.append(FOOTER_CTA)
    out.append("</section>")
    return doc_title, "\n".join(out)


def bump_fonts(html, delta=0.5):
    """全局字号 +delta：用户要求正文其余部分整体再加 0.5px。"""
    def f(m):
        return "font-size:%.1fpx" % (float(m.group(1)) + delta)
    return re.sub(r"font-size:([\d.]+)px", f, html)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "/tmp/feishu_doc.xml"
    dst = sys.argv[2] if len(sys.argv) > 2 else "out.html"
    doc_title, html = build(src)
    html = bump_fonts(html, 0.5)
    open(dst, "w", encoding="utf-8").write(html)
    open(dst + ".title.txt", "w", encoding="utf-8").write(doc_title)
    print(f"✓ {dst}  ({len(html)} chars)")
    print(f"  标题: {doc_title}")


if __name__ == "__main__":
    main()
