"""M0 — Khảo sát cấu trúc PDF báo cáo thường niên (chạy lại được).

Cách dùng:
    pip install pymupdf
    python profile_pdf.py data/techcombank-bao-cao-thuong-nien-2025-vie-update.pdf --out m0_report.json

Kiểm tra:
  1. Kích thước trang -> phát hiện trang đôi (spread)
  2. Số trang in ở góc trên trái/phải -> kiểm định quy luật PDF p -> (2p-2, 2p-1)
  3. Bảng (PyMuPDF find_tables) theo từng nửa trang + độ phủ con số trong chương BCTC
  4. Bảng / khối text vắt qua khe giữa (gutter)
  5. Chỉ số superscript (chú thích) dính vào chữ/số
  6. Thống kê ảnh: số lần đặt, số ảnh duy nhất, ảnh lặp lại
"""
import argparse
import collections
import json
import re

import pymupdf as fitz

NUM = re.compile(r"^\(?-?\d{1,3}(\.\d{3})+(,\d+)?\)?$|^\(?\d+,\d+\)?$")
HEADER_BAND = 45      # pt: vùng chứa số trang in ở mép trên
CORNER = 100          # pt: số trang nằm trong 100pt tính từ mép trái/phải


def halves(page):
    W, H = page.rect.width, page.rect.height
    if W > H:  # spread
        return [("L", fitz.Rect(0, HEADER_BAND, W / 2, H)), ("R", fitz.Rect(W / 2, HEADER_BAND, W, H))]
    return [("S", fitz.Rect(0, HEADER_BAND, W, H))]


def printed_numbers(page):
    W = page.rect.width
    left = right = None
    for x0, y0, x1, y1, w, *_ in page.get_text("words"):
        if y0 < HEADER_BAND and re.fullmatch(r"\d{1,3}", w):
            if x0 < CORNER:
                left = int(w)
            elif x0 > W - CORNER:
                right = int(w)
    return left, right


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--fs-start", type=int, default=147, help="trang PDF đầu tiên của BCTC")
    ap.add_argument("--fs-end", type=int, default=193, help="trang PDF cuối của BCTC")
    ap.add_argument("--out", default="m0_report.json")
    a = ap.parse_args()

    doc = fitz.open(a.pdf)
    rep = {"pdf_pages": doc.page_count, "has_outline": bool(doc.get_toc())}

    # 1-2. Spread + page map
    sizes = collections.Counter((round(p.rect.width), round(p.rect.height)) for p in doc)
    rep["page_sizes"] = {f"{w}x{h}": n for (w, h), n in sizes.items()}
    anomalies, page_map = [], []
    for i, p in enumerate(doc):
        pn = i + 1
        L, R = printed_numbers(p)
        expected = (2 * pn - 2, 2 * pn - 1) if pn > 1 else (None, None)
        page_map.append({"pdf_page": pn, "printed": [L, R], "expected": list(expected)})
        if (L, R) != expected:
            anomalies.append({"pdf_page": pn, "found": [L, R], "expected": list(expected),
                              "words": len(p.get_text("words"))})
    rep["page_rule"] = "pdf p -> printed (2p-2 | 2p-1); p=1 là bìa"
    rep["page_rule_anomalies"] = anomalies

    # 3. Bảng BCTC: độ phủ con số
    tot_nums = tot_cov = none_cells = 0
    low = []
    for pn in range(a.fs_start, a.fs_end + 1):
        p = doc[pn - 1]
        for side, clip in halves(p):
            nums = [w[4] for w in p.get_text("words", clip=clip) if NUM.match(w[4])]
            cells = []
            for t in p.find_tables(clip=clip).tables:
                for row in t.extract():
                    for c in row:
                        if c is None:
                            none_cells += 1
                        else:
                            cells += c.split()
            have = collections.Counter(c for c in cells if NUM.match(c))
            need = collections.Counter(nums)
            cov = sum(min(v, have[k]) for k, v in need.items())
            tot_nums += len(nums)
            tot_cov += cov
            if nums and cov / len(nums) < 0.9:
                low.append({"pdf_page": pn, "side": side, "numbers": len(nums), "covered": cov})
    rep["fs_table_coverage"] = {"number_tokens": tot_nums, "covered": tot_cov,
                                "ratio": round(tot_cov / max(1, tot_nums), 4),
                                "none_cells": none_cells, "low_coverage_halves": low}

    # 4. Bảng vắt qua gutter
    spanning, n_tables = [], 0
    for i, p in enumerate(doc):
        W = p.rect.width
        if W <= p.rect.height:
            continue
        for t in p.find_tables().tables:
            n_tables += 1
            x0, _, x1, _ = t.bbox
            if x0 < W / 2 - 20 and x1 > W / 2 + 20:
                spanning.append({"pdf_page": i + 1, "printed": [2 * i, 2 * i + 1],
                                 "rows": t.row_count, "cols": t.col_count})
    rep["tables_total"] = n_tables
    rep["tables_spanning_gutter"] = spanning

    # 5. Superscript
    sup = []
    for i, p in enumerate(doc):
        for b in p.get_text("dict")["blocks"]:
            for line in b.get("lines", []):
                spans = line["spans"]
                for j, s in enumerate(spans):
                    if s["flags"] & 1 and s["text"].strip():
                        prev = spans[j - 1]["text"][-20:] if j else ""
                        sup.append({"pdf_page": i + 1, "prev": prev, "sup": s["text"]})
    rep["superscripts"] = sup

    # 6. Ảnh
    use = collections.defaultdict(list)
    for i, p in enumerate(doc):
        for info in p.get_image_info(xrefs=True):
            use[info["xref"]].append(i + 1)
    rep["images"] = {"placements": sum(len(v) for v in use.values()), "unique": len(use),
                     "repeated_gt2": sum(1 for v in use.values() if len(v) > 2)}

    json.dump(rep, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in rep.items() if k not in ("superscripts",)},
                     ensure_ascii=False, indent=1)[:3000])


if __name__ == "__main__":
    main()