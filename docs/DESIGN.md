# DESIGN — Chatbot Báo cáo Thường niên Techcombank 2025

> Tài liệu thiết kế MVP · Kiến trúc · Tech stack · Cấu trúc dự án
> Trạng thái: Draft · Package Python tạm: `ircb` (đổi khi chốt tên dự án)

---

## 0. TL;DR

- **Nguyên tắc số 1:** *LLM viết câu, code xác minh.* Số liệu, số trang, đơn vị và phép tính đều do code xử lý.
- **Tài liệu là 196 trang đôi (spread A3).** Mỗi trang PDF chứa 2 trang in, nên mọi thứ (text, bảng, chunk, citation) phải tách theo **nửa trang**, và phải xử lý riêng 6 bảng vắt qua khe giữa.
- **Hai đường trả lời:**
  (a) RAG trên text, cho câu hỏi định tính và số liệu ở phần tổng quan.
  (b) **Fact lookup** trên bảng BCTC đã cấu trúc hóa, cho số liệu chi tiết.
  Cả hai đều đi qua verifier.
- **Ba thang đơn vị cùng tồn tại:** `nghìn tỷ đồng` (KPI), `tỷ đồng` (bảng tổng quan, công ty con), `triệu đồng` (BCTC). Chênh lệch giữa chúng lên tới 10⁶ lần.
- Stack: Python, PyMuPDF, bge-m3, **Qdrant** (dense + sparse BM25, hybrid fusion phía server), **PostgreSQL** (facts, sessions; SQLAlchemy + Alembic), LiteLLM, RAGAS (chỉ dùng cho eval). Chạy offline được.
- **Hai chế độ chạy, cùng một code:** *production* dùng Qdrant server + Postgres (docker-compose). *Chấm bài* dùng Qdrant embedded + SQLite, không cần Docker. Chọn chế độ bằng env var.
- **Monorepo, core độc lập với giao diện:** toàn bộ logic nằm trong thư viện `core`. CLI (REPL + batch, phục vụ chấm bài), API FastAPI và web Next.js chỉ là các lớp vỏ mỏng gọi chung một `AnswerService`.
- **Web UI phục vụ đúng nhu cầu "kiểm chứng trong 5 giây":** bấm vào `[tr. N]` là mở ngay ảnh trang in, có tô sáng vùng chứa con số.

---

## 1. Bối cảnh & mục tiêu

| | |
|---|---|
| **User** | Analyst IR, hiểu tài chính, đọc tiếng Việt, không quan tâm stack |
| **Job-to-be-done** | Trả lời nhanh câu hỏi về báo cáo thường niên, paste thẳng vào email gửi nhà đầu tư |
| **Điều kiện thất bại** | Một con số sai hoặc sai trang là user bỏ tool |
| **Định nghĩa thành công** | Mỗi claim kiểm chứng được trong ~5 giây bằng cách mở đúng trang in |

### 1.1 Mục tiêu đo được

| Metric | Mục tiêu | Cách đo |
|---|---|---|
| Page map đúng | **100%** (392 trang in) | Quy luật + kiểm tra header tự động + đối chiếu tay 20 trang |
| Độ phủ con số trong bảng BCTC | ≥ 99% (baseline M0: 98,6%) | `profile_pdf.py` |
| Citation correctness | ≥ 95% | Verifier + chấm tay |
| Answer correctness (số + đơn vị) | ≥ 80% trên eval set riêng | Chấm tay |
| Refusal recall / false refusal | ≥ 90% / ≤ 15% | Chấm tay |
| Hallucination-leak (số sai lọt qua verifier) | **0** | Chấm tay |
| Latency p50 / p95 | < 6s / < 12s | Trace |

> Ngưỡng chỉ là mục tiêu ban đầu. Báo cáo số thật, kể cả khi không đạt.

---

## 2. Kết quả khảo sát tài liệu (M0)

> Nguồn: `scripts/profile_pdf.py` (chạy ~1 phút trên CPU) cộng kiểm tra trực quan các trang render. PDF: Adobe InDesign 21, 197 trang PDF, không có bookmark/outline.

| # | Phát hiện | Bằng chứng | Hệ quả thiết kế |
|---|---|---|---|
| 1 | **196/197 trang là spread** 1191×842pt (A3 ngang = 2 trang A4). Chỉ bìa là trang đơn. | `page_sizes` | Đơn vị xử lý là **nửa trang**, không phải trang PDF |
| 2 | Số trang in nằm ở **góc trên** (x≈43 bên trái, x≈1140 bên phải), không phải ở footer. Quy luật **PDF p → tr. (2p−2 \| 2p−1)** đúng với 190/190 trang có số. | `page_rule_anomalies` | Page map = quy luật + kiểm tra header. Không cần heuristic phức tạp |
| 3 | 6 trang không đánh số (PDF 5, 13, 23, 51, 73, 146) đều là **trang mở chương** (tr. 8, 24, 44, 100, 144, 290), khớp mục lục. | Mục lục tr. 2–3 | Vẫn áp quy luật, đánh dấu `is_divider` |
| 4 | Header lặp: "Báo cáo thường niên 2025 \| N" (trái), **"<Tên chương> \| N"** (phải). PyMuPDF gộp header hai nửa thành 1 block vắt qua gutter. | 274 block vắt gutter, phần lớn là header | Header vừa là furniture cần bỏ, vừa là **nguồn metadata chương miễn phí**. Tách theo *word*, không theo *block* |
| 5 | **Mục lục** (tr. 2–3): 6 chương. BCTC hợp nhất kiểm toán từ tr. 290 (PDF 146–193). Danh mục viết tắt ở tr. 386–387, Phụ lục GRI từ tr. 388. Chỉ có **BCTC hợp nhất** (`TCTD-HN`), không có BCTC riêng lẻ. | Text tr. 2 | `config/sections.json` sinh từ mục lục. Bỏ hẳn nhánh "hợp nhất vs riêng lẻ" |
| 6 | Bảng BCTC **gần như không có đường kẻ dọc** (chỉ vạch ngang mờ và cột tô nền). pdfplumber `lines` **trả `None` cho cả cột 31/12/2024** mà không báo lỗi. pdfplumber `text` băm vụn chữ ("NỢ PHẢ \| I TRẢ"). PyMuPDF `find_tables` đọc đúng. | Thử trên PDF 150 | **PyMuPDF `find_tables` làm mặc định**, kèm một bộ kiểm tra độ phủ |
| 7 | Độ phủ con số của `find_tables` trên toàn chương BCTC: **2124/2154 = 98,6%**. 6 nửa trang dưới 90%. | `fs_table_coverage` | Fallback: gom từ theo tọa độ cho các nửa trang có độ phủ thấp |
| 8 | **6 bảng vắt qua khe giữa** (PDF 18, 74, 119, 177, 188). Ví dụ tr. 374–375: bảng 25×10, **nhãn dòng chỉ có ở trang trái**, trang phải toàn số. Cắt cứng ở W/2 sẽ sinh ra số mồ côi. | `tables_spanning_gutter` | Bảng vắt gutter được trích trên **cả spread** và cite **`[tr. N, N+1]`** |
| 9 | **Ba thang đơn vị**: KPI "1.192 / Nghìn tỷ đồng" (tr. 5) · bảng tổng quan "Đơn vị: Tỷ đồng" (tr. 14: 1.192.344) · BCTC "Triệu đồng" (tr. 297: 1.192.344.137). Đơn vị có thể nằm ở header cột, ở dòng "Đơn vị: …" phía trên bảng, hoặc ở dòng riêng dưới số trong ô KPI. | Render tr. 4–5, 14, 297 | Mỗi fact bắt buộc có `unit`. Unit được phát hiện theo thứ tự ưu tiên: header cột → "Đơn vị:" gần nhất phía trên → mặc định của chương |
| 10 | **Mũi tên ▲/▼ trên ô KPI là hình vector**, text chỉ còn "18,2% N/N". **Mất dấu tăng/giảm.** | Text PDF 25 so với render | Đọc hướng mũi tên từ `get_drawings()` (§5.4, đã kiểm chứng ở finding #20). Không đọc được thì `direction=unknown` và không được nói "tăng/giảm" |
| 11 | **Footnote superscript dính vào chữ**: "Dư nợ tín dụng**1**", "khách hàng**2**" (17 span có cờ superscript, không span nào dính vào con số tài chính). | `superscripts` | Bỏ span có `flags & 1` khi build text/fact, giữ footnote làm metadata |
| 12 | **Thứ tự đọc**: thứ tự stream mặc định của InDesign đúng cho văn bản nhiều cột. `sort=True` **làm xen kẽ hai cột**. Riêng ô KPI thì thứ tự bị xáo (số, mô tả, đơn vị bị tách). | So sánh PDF 8 | Dùng thứ tự stream mặc định cho văn xuôi. Ô KPI dùng parser riêng theo tọa độ |
| 13 | Cùng một nhãn xuất hiện 2 lần trong 1 bảng: "Cho vay khách hàng" **757.118.751** (dòng cha, thuần) và **767.617.129** (dòng con, TM 9) [tr. 297]. Thụt lề chỉ lệch **4pt**. | Tọa độ word | Fact store lưu `row_level` (từ x0 + bold) và `parent_label` |
| 14 | **"Mâu thuẫn" thực chất là khác định nghĩa**: Dư nợ tín dụng theo NHNN 758.285 tỷ [tr. 14] ≈ 758,3 nghìn tỷ [tr. 48] so với cho vay KH 767.617.129 triệu [tr. 297]. | Các trang trên | Chính sách conflict phải phân biệt **làm tròn**, **khác định nghĩa** và **khác thật sự** (§5.13) |
| 15 | Text layer sạch: Unicode NFC, không có dấu tiếng Việt rời (0 combining mark). Font ProximaNova, ToUnicode tốt. | Thống kê ký tự | **Không cần OCR cho text.** Có `\xa0`, `‑` (non-breaking hyphen), `–` → chuẩn hóa trước khi parse số |
| 16 | 496 lần đặt ảnh / **252 ảnh duy nhất**, 11 ảnh lặp > 2 lần (logo, nền). Biểu đồ (vd. tr. 80 "Số lượng khách hàng TCBS") và sơ đồ ("6 trụ cột") là **vector có nhãn text**. OCR thử 272 ảnh lớn: không tìm được ảnh raster nào chứa số liệu vắng mặt trong text layer. | `images`, OCR | Ảnh: lọc + phân loại nhẹ, không OCR hàng loạt. Đề nói "một vài ảnh không phải trang trí", nên **còn ~40 ảnh mid-size cần duyệt tay** (§13) |
| 17 | Bảng viết tắt tr. 386–387 là **6 bảng con 2 cột** trên một spread (~170 mục), có mục nhiều dòng. | Render PDF 194 | Parse bằng `find_tables` theo từng nửa trang, rồi ghép dòng tiếp nối |
| 18 | Số viết không nhất quán trong cùng một trang: "hơn **7100** tỷ đồng" (không phân cách) cạnh "**7.109** Tỷ đồng" [tr. 76–77]. | PDF 39 | `numbers_vn` phải nhận cả số không có dấu phân cách. Verifier so khớp theo giá trị, không theo chuỗi |
| 19 | **Ô KPI bị trộn khi đọc theo stream** [tr. 59]: "Dư nợ vay · Nghìn tỷ đồng ×4 · 328,1 · 26,9% N/N · Thu nhập lãi thuần · 9,4% N/N · 21,9 · …". Chỉ đọc text thì **không biết 9,4% thuộc chỉ tiêu nào**. Đơn vị có thể nằm **bên phải** số (tr. 59) hoặc **bên dưới** (tr. 5). | Text so với render tr. 59 | KPI parser theo tọa độ là **bắt buộc**. Prototype ghép đúng 4/4 ô ở tr. 59 và 13/13 ô ở tr. 5 |
| 20 | **Mũi tên đọc được từ vector:** tam giác 6 điểm sát bên trái con số %. Mũi tên lên màu trắng, **mũi tên xuống màu đỏ**. Ví dụ giảm thật: CIR của TCBS ▼ 0,5% [tr. 81], text chỉ là "0,5%". | `get_drawings()` trên tr. 48, 59, 81 | `direction` lấy từ hình học (đỉnh tam giác) và màu, có golden test cả UP lẫn DOWN |
| 21 | **10 câu mẫu dồn vào rất ít trang:** 6 câu ở tr. 4–5 (một spread), 1 câu tr. 59, 2 câu ở bảng viết tắt tr. 386–387, 1 câu ngoài phạm vi. **Không câu nào chạm BCTC**, không có follow-up hay tính toán. | `sample_questions.json` | Bộ câu ẩn "covering ground the 10 do not" gần như chắc chắn sẽ hỏi BCTC, bảng, so sánh và đa lượt. **Tối ưu theo 10 câu là bẫy.** Eval set riêng phải phủ phần còn lại (§10.4) |
| 22 | Chuỗi "2027" **không xuất hiện** trong tài liệu. | Tìm kiếm toàn văn | Có thể dùng làm tín hiệu từ chối khi câu hỏi nhắc một kỳ không có trong tài liệu (§5.9) |

### 2.1 Phân rã tài liệu theo vùng

| Vùng | Trang in | Trang PDF | Đặc điểm | Chiến lược |
|---|---|---|---|---|
| Bìa, mục lục, điểm nhấn | 1–7 | 1–4 | Ô KPI, ảnh | KPI parser |
| Ch.1 Tầm nhìn | 8–23 | 5–12 | Văn xuôi + bảng kết quả (tỷ đồng) | Văn xuôi + bảng |
| Ch.2 Câu chuyện | 24–43 | 13–22 | Văn xuôi, timeline vắt gutter | Văn xuôi |
| Ch.3 Thành tựu (KQKD, RBG, CIBG, công ty con) | 44–99 | 23–50 | **Mật độ số liệu kinh doanh cao nhất**, KPI tile, biểu đồ vector | KPI parser + văn xuôi + bảng |
| Ch.4 Chuyển đổi | 100–143 | 51–72 | Văn xuôi, sơ đồ | Văn xuôi |
| Ch.5 Quản trị, rủi ro, PTBV | 144–289 | 73–145 | Văn xuôi dài, bảng nghị quyết, bảng ESG | Văn xuôi + bảng |
| Ch.6 BCTC hợp nhất | 290–385 | 146–193 | B02/B03/B04/B05, thuyết minh đánh số | **Fact store** + chunk bảng |
| Viết tắt, GRI | 386–393 | 194–197 | Bảng tra cứu | Glossary + chunk bảng |

---

## 3. Phạm vi

### 3.1 Sáu hạng mục bắt buộc

| # | Hạng mục | Thiết kế |
|---|---|---|
| F1 | Ingestion | Spread → 2 nửa trang → layout (văn xuôi / bảng / KPI / furniture) → chunk + fact store → index hybrid |
| F2 | Chatbot đa lượt | REPL, viết lại câu hỏi theo lịch sử, giữ `period` / `metric` của lượt trước |
| F3 | Citation | Model trả `chunk_id` / `fact_id`, số trang lấy từ metadata, render `[tr. N]` / `[tr. N, M]` |
| F4 | Từ chối có căn cứ | 4 lớp: **period guard** · score gate · model `not_found` · verifier fail |
| F5 | Eval | 10 câu mẫu + 30–40 câu tự xây, chấm tay, RAGAS đã kiểm định |
| F6 | Tái lập | Env vars, ship index, 1 lệnh, batch, video, SUBMISSION.md |

### 3.2 Depth track

| | Track |
|---|---|
| Chính | **Document Intelligence** |
| Phụ | **Retrieval & Reasoning** (gọn) |

**Lý do:** khảo sát cho thấy rủi ro lớn nhất nằm ở *trích xuất*, không ở *retrieval*. Cụ thể là spread, bảng vắt gutter, ba thang đơn vị, mất dấu ▲/▼ và nhãn trùng lặp. Retrieval tốt đến đâu cũng không cứu được một con số đã bị gán sai dòng hay sai đơn vị từ lúc ingest. Độ phủ bảng 98,6% ngay từ baseline cho thấy track này **làm xong được trong ngân sách thời gian**.

Track phụ chỉ giữ những phần rẻ mà hiệu quả cao: hybrid BM25 + dense, mở rộng glossary, tool tính toán. Phần benchmark embedding làm sau cùng, cắt được nếu thiếu giờ.

### 3.3 Giao diện

| Lớp | Vai trò | Ưu tiên |
|---|---|---|
| CLI: REPL + batch | **Kênh chấm bài** (đề yêu cầu chạy batch không cần người gõ) | Bắt buộc |
| API (FastAPI) | Kênh dùng chung cho web và cho tích hợp sau này | Cao |
| Web (Next.js) | Chat + **trình xem trang in có tô sáng bằng chứng** | Sau khi core và eval xong |

> Đề không chấm web UI. Web được làm vì nó giải trực tiếp bài toán "kiểm chứng trong 5 giây", nhưng **không được lấy giờ của core, verifier và eval**.

### 3.4 Out of scope

Auth · multi-user (mỗi phiên chat chỉ là một `session_id`, không có tài khoản) · deploy lên cloud, orchestration, CI · fine-tuning · design system tự xây (dùng thư viện component có sẵn) · OCR hàng loạt · reranker (chỉ thêm nếu eval cho thấy `R-miss` cao).

---

## 4. Kiến trúc tổng thể

```mermaid
flowchart TB
    subgraph ING["Ingestion: chạy 1 lần, ship kết quả"]
        PDF[PDF 197 trang] --> SP[Spread splitter<br/>PDF p → nửa L/R<br/>tr. 2p-2 / 2p-1]
        SP --> HDR[Header parser<br/>số trang + tên chương<br/>→ verify page map]
        SP --> LAY[Layout analyzer<br/>word/span + drawings]
        LAY --> FUR[Furniture filter]
        LAY --> GT{Bảng vắt gutter?}
        GT -- có --> TS[Trích trên cả spread<br/>cite tr. N, N+1]
        GT -- không --> TH[find_tables theo nửa trang]
        TS & TH --> TQ[Table QA<br/>độ phủ số · cột None<br/>→ fallback tọa độ]
        LAY --> KPI[KPI tile parser<br/>số + đơn vị + nhãn]
        LAY --> PR[Prose extractor<br/>stream order, bỏ superscript]
        TQ --> FN[Fact normalizer<br/>numbers_vn + unit + row_level]
        KPI --> FN
        FN --> FS[(Facts DB<br/>Postgres / SQLite)]
        TQ & PR & KPI --> CK[Chunker<br/>1 chunk ⊂ 1 trang in<br/>trừ bảng vắt gutter]
        CK --> CH[(chunks.jsonl)]
        CH --> EMB[bge-m3 dense<br/>+ BM25 sparse] --> VP[(vectors.parquet<br/>artefact ship)]
        VP --> QD[(Qdrant<br/>chunks · facts)]
        FS --> EMB
        PDF --> GL[Glossary tr. 386–387] --> GJ[(glossary.json)]
    end

    subgraph QRY["Query time"]
        U[Analyst] --> REPL --> QR[Rewriter<br/>standalone + period + metric]
        QR --> QE[Glossary expander]
        QE --> HR[Hybrid retriever<br/>Qdrant: dense + sparse<br/>RRF phía server]
        HR --> GATE{Score gate}
        GATE -- thấp --> REF[Từ chối + trang gợi ý]
        GATE -- đủ --> GEN[Generator LLM<br/>JSON claims]
        GEN <--> T1[lookup_fact]
        GEN <--> T2[calc: growth / ratio / diff]
        GEN --> VER[Verifier deterministic]
        VER -- fail --> REF
        VER -- pass --> REN[Renderer tr. N]
        REN --> REPL
        REF --> REPL
    end
    FS -.-> T1
    FS -.-> T2
    FS -.-> VER
    QD -.-> HR
    QD -.-> T1
    GJ -.-> QE
```

### 4.1 Nguyên tắc thiết kế

1. **Đơn vị nguyên tử là nửa trang** (= 1 trang in). Mọi artefact đều mang `printed_page`.
2. **Deterministic ở nơi rủi ro cao:** page map, đơn vị, phép tính, citation đều làm bằng code.
3. **Không tin parser một cách mù quáng:** mỗi bảng trích ra đều qua Table QA (độ phủ số, cột rỗng). Kết quả ghi vào `ingest_report.json`.
4. **Giữ chuỗi gốc:** mỗi số luôn đi kèm `raw`, `unit_raw` và `bbox`.
5. **Tách phần riêng của tài liệu khỏi code:** các hằng số như `HEADER_BAND`, ranh giới chương, override nằm trong `config/`.

### 4.2 Kiến trúc ứng dụng (các lớp)

```mermaid
flowchart LR
    subgraph Clients
        WEB[Web · Next.js<br/>chat + page viewer]
        CLI[CLI · REPL + batch]
    end
    subgraph API["API · FastAPI"]
        R1[/POST /v1/chat · SSE/]
        R2[/GET /v1/pages/:printed/image/]
        R3[/GET /v1/facts · /v1/health/]
    end
    subgraph CORE["core (thư viện Python, không phụ thuộc web)"]
        SVC[AnswerService]
        RET[retrieval] --- ANS[answer: rewriter · generator · tools · verifier]
        ING[ingestion]
    end
    QD[(Qdrant<br/>server · hoặc embedded)]
    DB[(PostgreSQL · hoặc SQLite<br/>facts · sessions · traces)]
    ART[(index/ artefact<br/>chunks · vectors.parquet · facts.jsonl · page_map)]

    WEB -->|HTTP/SSE| API
    CLI -->|gọi trực tiếp| SVC
    API --> SVC
    SVC --> RET & ANS
    RET --> QD
    ANS --> DB
    API --> DB
    ING -->|build offline| ART
    ART -->|ircb index load<br/>không embed lại| QD & DB
```

**Quy tắc phụ thuộc** (kiểm tra bằng `import-linter` để đảm bảo chiều phụ thuộc):
- `core` không import `fastapi`, `apps.*` hay bất cứ thứ gì về HTTP.
- `apps/api` và `apps/cli` chỉ gọi `core` qua `AnswerService`, `PageRenderer` và `FactRepository`. Không có logic nghiệp vụ trong route.
- `apps/web` chỉ nói chuyện với API qua **TypeScript types sinh từ OpenAPI** (`openapi-typescript`), không viết tay kiểu dữ liệu.
- Lịch sử hội thoại do lớp ứng dụng giữ (CLI giữ trong bộ nhớ, API lưu DB theo `session_id`) rồi truyền vào `AnswerService`. Core **không có trạng thái**.

### 4.3 Lưu trữ: artefact là nguồn sự thật, DB là lớp phục vụ

```
ingestion (chậm, chạy 1 lần) ──► index/  (artefact bất biến, có version, SHIP cái này)
                                   │  chunks.jsonl · vectors.parquet · facts.jsonl · page_map.json · manifest.json
                                   ▼
                    ircb index load   (vài giây, không gọi model embedding)
                       ├──► Qdrant  collections: chunks, facts
                       └──► SQL DB  bảng: facts, documents, index_versions
```

- **Vì sao không ship thẳng dữ liệu của DB:** snapshot của Qdrant server và thư mục của Qdrant embedded khác định dạng, dump của Postgres và file SQLite cũng khác nhau. Ship artefact trung lập (Parquet/JSONL) thì nạp được vào **cả hai chế độ** bằng cùng một loader, diff được giữa các lần build, và không bị khóa vào phiên bản DB.
- **Tự nạp khi khởi động:** API/CLI so `manifest.index_version` với bảng `index_versions`. Nếu thiếu hoặc lệch thì tự chạy `index load`. Nhờ vậy người chấm chỉ cần một lệnh.
- **Idempotent:** point ID trong Qdrant là UUIDv5 sinh từ `chunk_id`/`fact_id`, nên nạp lại không tạo bản trùng.
- **Có `doc_id` ngay từ đầu** (payload Qdrant và cột SQL) để mở rộng lên nhiều tài liệu mà không phải migrate lại.

**API contract (rút gọn):**

| Endpoint | Mô tả |
|---|---|
| `POST /v1/chat` | Body `{session_id?, message}`. Trả **SSE**: `status` (đang tìm, đang kiểm tra) → `answer` (claims đã verify + citations) → `done` (trace_id, latency, cost) |
| `GET /v1/sessions/{id}` | Lịch sử hội thoại |
| `GET /v1/pages/{printed}/image?highlight=<chunk_id\|fact_id>` | PNG trang in (render nửa spread), tô sáng bbox bằng chứng. Có cache |
| `GET /v1/facts?q=&period=` | Tra cứu fact store (debug, cho analyst) |
| `GET /v1/traces/{trace_id}` | Trace JSON (chỉ bật khi `APP_ENV=dev`) |
| `GET /v1/health` | Index đã load, manifest, model đang dùng |

> SSE chỉ stream **trạng thái**, không stream token. Câu trả lời chỉ được gửi sau khi verifier chạy xong, vì stream token thô sẽ cho user nhìn thấy những con số chưa được kiểm tra.

---

## 5. Thiết kế chi tiết

### 5.1 Spread splitter & page map

```
pdf_page = 1            → printed = [1]            (bìa, trang đơn)
pdf_page = p ≥ 2        → L: 2p−2 , R: 2p−1
```

1. Nếu `width > height` thì tách hai clip `[0, W/2]` và `[W/2, W]`.
2. **Kiểm tra:** đọc word dạng số trong vùng `y < 45pt`, ở góc trái (`x < 100`) và góc phải (`x > W−100`). Số đọc được phải khớp quy luật. Lệch ở bất kỳ trang nào thì **fail build**, không đi tiếp với cảnh báo.
3. Trang không có số (6 trang mở chương) vẫn áp quy luật, gắn `is_divider=true`.
4. Lấy tên chương từ header phải (text sau khi bỏ số trang) → `chapter`.
5. Tạo `page_map.json` và unit test khẳng định 190/190 trang khớp.

> Phần riêng cho tài liệu này là quy luật `2p−2`. Để dùng cho tài liệu khác, page mapper chạy chế độ **"đọc số trong header/footer rồi kiểm tra đơn điệu"**, còn quy luật chỉ là một lớp kiểm tra. Ghi rõ điều này trong SUBMISSION ở câu hỏi "cái gì sống sót qua 100 tài liệu".

### 5.2 Layout analyzer & furniture

- Làm việc ở mức **word/span** (`get_text("dict")`), không ở mức block, vì block header bị gộp qua gutter.
- Furniture: vùng `y < 45pt`, chuỗi "Báo cáo thường niên 2025", tên chương lặp lại, mã biểu mẫu `B0x/TCTD-HN` và dòng "tại ngày 31 tháng 12 năm 2025…" ở đầu trang BCTC. Mã `B0x` được giữ lại làm metadata `statement`.
- Bỏ span superscript (`flags & 1`) khỏi text, lưu thành `footnote_refs`.
- Chuẩn hóa ký tự: `\xa0` → space, `‑` → `-`, `–` giữ nguyên trong văn xuôi nhưng chuẩn hóa trong số âm và khoảng năm.

### 5.3 Table extraction

| Bước | Chi tiết |
|---|---|
| 1. Phát hiện | `page.find_tables()` trên **cả spread** trước. Bảng nào có bbox vắt qua `W/2 ± 20` thì gắn `spans_gutter`. Các bảng còn lại trích lại theo nửa trang |
| 2. Header nhiều tầng | Forward-fill ô `None` theo hàng (merge ngang) và theo cột (merge dọc). Ghép header thành đường dẫn, vd. `2025 > Thực hiện`, `% So sánh với > Kế hoạch` |
| 3. Thứ bậc dòng | `row_level` tính từ x0 của word đầu dòng (bucket 4pt) cộng font bold. Gắn `parent_label` theo dòng có level nhỏ hơn gần nhất phía trên |
| 4. Dòng không nhãn | Dòng chỉ có số và nằm ngay sau nhóm → gắn `label = "Tổng (" + parent + ")"`, `is_total=true` |
| 5. Table QA | Độ phủ = số con số trên trang lọt vào bảng / tổng con số trên trang. Dưới 0,95 hoặc có cột toàn `None` thì chạy **fallback gom theo tọa độ** (cụm theo y, cột theo x anchor của header), rồi đo lại. Ghi kết quả vào `ingest_report.json` |
| 6. Ngữ cảnh | Tiêu đề bảng = heading gần nhất phía trên (vd. "12. CHỨNG KHOÁN ĐẦU TƯ", "12.1. …"), `note_no`, `statement`, `unit` |
| 7. Bảng tiếp nối | Trang có "(tiếp theo)" và cùng `note_no` thì gắn `continues=<table_id>`. **Không** gộp chunk qua trang để giữ citation, nhưng lặp lại header ngữ cảnh |

Render bảng thành markdown để làm chunk, đồng thời **bóc thành fact** (§5.5).

### 5.4 KPI tile parser

Ô KPI (tr. 4–5, 48, 77…) có cấu trúc: *nhãn* → *số lớn* → *đơn vị* → *mô tả/so sánh*, nhưng stream order bị xáo.

**Bắt buộc.** 6/10 câu mẫu được trả lời từ ô KPI (finding #19, #21).

- **Nhận diện:** span có cỡ chữ ≥ 2,2× median của nửa trang và chứa chữ số (hoặc "TOP 1").
- **Ghép ô:** với mỗi số lớn, xét các span có tâm x trong khoảng ±70pt:
  - *Nhãn* = **dòng gần nhất** phía trên (≤ 60pt), dừng khi gặp khoảng trống lớn, để không kéo theo đoạn văn phía trên (lỗi đã thấy ở prototype tr. 59).
  - *Đơn vị* = span ngay **bên phải** (cùng baseline, tr. 59) **hoặc** ngay **bên dưới** (tr. 5).
  - *Mô tả/so sánh* = các dòng phía dưới cho tới đường kẻ ngăn ô kế tiếp.
- **Chiều thay đổi:** tìm drawing nhỏ (< 12pt) cách mép trái con số % dưới 15pt và lệch tâm y dưới 6pt. Phân loại theo đỉnh tam giác (1 điểm ở y nhỏ nhất thì là UP) và dùng màu làm kiểm tra chéo (đỏ thì là DOWN). Không tìm thấy thì `direction=unknown`.
- **Output:** fact `source="kpi"` gồm `label`, `value`, `unit`, `change_value`, `change_basis` (`N/N`, `so với năm trước`, `CAGR 2018–2025`), `direction`, `bbox`. Đồng thời sinh một chunk câu chuẩn hóa, vd. *"Dư nợ vay (Khối Ngân hàng Bán lẻ): 328,1 nghìn tỷ đồng, tăng 26,9% so với cùng kỳ năm trước"*.
- **Ngữ cảnh ô:** tiêu đề vùng gần nhất ("Điểm nhấn 2025") và chapter/section từ header phải (tr. 59 thuộc mục RBG) được prepend vào chunk. Nếu thiếu thì "Dư nợ vay" không biết là của khối nào.
- **Golden test:** 13 ô tr. 5, 4 ô tr. 59, 9 ô tr. 48, và CIR ▼ tr. 81.

### 5.5 Fact Store (bảng `facts` trong SQL DB + collection `facts` trong Qdrant)

**Vì sao cần:** truy vấn kiểu "Chứng khoán đầu tư sẵn sàng để bán cuối 2024 là bao nhiêu?" cần đúng ô (dòng × cột). Retrieval trên chunk markdown thường lấy đúng bảng, nhưng LLM vẫn có thể đọc nhầm cột hoặc nhầm dòng cha/con (finding #13). Fact store biến bước đọc ô thành truy vấn deterministic.

Schema khai báo bằng SQLAlchemy 2.0, migrate bằng Alembic, chạy trên **PostgreSQL** (production) hoặc **SQLite** (chấm bài). Không dùng tính năng riêng của Postgres trong bảng này để giữ tính di động.

```sql
CREATE TABLE facts (
  fact_id       TEXT PRIMARY KEY,   -- p297_t02_r14_c2
  doc_id        TEXT NOT NULL,      -- "tcb-ar-2025"
  printed_pages TEXT,               -- "297" hoặc "374,375"
  chapter       TEXT,               -- từ header
  statement     TEXT,               -- B02/TCTD-HN | B03 | B04 | B05 | NULL
  note_no       TEXT,               -- "12.1"
  table_title   TEXT,
  label         TEXT,               -- "Chứng khoán nợ"
  label_norm    TEXT,               -- lower, bỏ dấu, cho tìm kiếm
  parent_label  TEXT,
  row_level     INT,
  is_total      INT,
  col_path      TEXT,               -- "31/12/2024" | "2025 > Kế hoạch"
  period        TEXT,               -- "2024-12-31" | "FY2025"
  value         NUMERIC(38,6),      -- Decimal, không dùng float
  unit          TEXT,               -- "triệu đồng" | "tỷ đồng" | "nghìn tỷ đồng" | "%"
  value_vnd     NUMERIC(38,0),      -- quy đổi về đồng (NULL nếu %)
  raw           TEXT,               -- "(415.884)"
  source        TEXT,               -- "table" | "kpi"
  pdf_page      INT,
  bbox          TEXT                -- "[x0,y0,x1,y1]" của ô, để web tô sáng
);
CREATE INDEX ix_facts_lookup ON facts (doc_id, statement, note_no, period);
```

- Số âm `(415.884)` → `-415884`. `-` trong ô số → `0` và `raw='-'`.
- `period` suy ra từ header cột (`31/12/2025`, `2025`, `Năm 2024`…). Cột % hoặc so sánh thì `period=NULL`, `unit='%'`.
- Ước lượng: ~2.000–4.000 fact cho chương BCTC và vài trăm fact từ KPI và bảng tổng quan.

**Tool cho LLM:**

| Tool | Input | Output |
|---|---|---|
| `lookup_fact(query, period?, statement?)` | Mô tả chỉ tiêu | (1) Hybrid search trên **collection `facts` của Qdrant** (text = `table_title > parent_label > label · col_path`), lọc payload theo `period`/`statement` → (2) lấy bản ghi đầy đủ từ SQL theo `fact_id` → top-5 kèm `value`, `unit`, `printed_pages` |
| `growth(fact_id_a, fact_id_b)` | 2 fact_id | `%`, tính bằng Decimal, **từ chối nếu khác unit hoặc khác loại chỉ tiêu** |
| `ratio(fact_id_a, fact_id_b)` | 2 fact_id | Tỷ lệ |
| `diff(fact_id_a, fact_id_b)` | 2 fact_id | Chênh lệch, giữ unit |
| `convert(fact_id, to_unit)` | | Đổi triệu ↔ tỷ ↔ nghìn tỷ, bằng code |

> Tool tính toán **chỉ nhận `fact_id`, không nhận số do model gõ**. Đây là câu trả lời trực tiếp cho câu hỏi của đề: *"Where should a bank not put a language model at all?"*

### 5.6 Chunking

| Loại | Chiến lược |
|---|---|
| Văn xuôi | Theo đoạn/heading trong **1 nửa trang**, 300–500 token. Prepend `chapter > heading` |
| Bảng (nửa trang) | 1 bảng = 1 chunk markdown. Bảng dài thì chia theo nhóm dòng và **lặp header**. Prepend `statement · note_no · table_title · Đơn vị: …` |
| Bảng vắt gutter | 1 chunk với `printed_pages=[N, N+1]` (ngoại lệ duy nhất của quy tắc 1 chunk ⊂ 1 trang) |
| KPI | 1 chunk / nhóm ô KPI dạng câu chuẩn hóa: "Tổng tài sản: 1.192 nghìn tỷ đồng (tăng 21,8% so với năm trước)" |
| Divider, ảnh trang trí | Bỏ |

Schema chunk:
```json
{
  "chunk_id": "p149R_t02", "pdf_page": 149, "half": "R",
  "printed_pages": [297], "chapter": "Báo cáo tài chính",
  "statement": "B02/TCTD-HN", "note_no": null,
  "content_type": "table", "unit": "triệu đồng",
  "text": "B02/TCTD-HN · Báo cáo tình hình tài chính hợp nhất · Đơn vị: triệu đồng\n| Chỉ tiêu | TM | 31/12/2025 | 31/12/2024 |\n|---|---|---|---|\n| Cho vay khách hàng | | 757.118.751 | 623.634.271 |\n|  └ Cho vay khách hàng | 9 | 767.617.129 | 631.724.964 |",
  "fact_ids": ["p149R_t02_r05_c2", "..."],
  "bbox": [596, 120, 1150, 520]
}
```

### 5.7 Chuẩn hóa số kiểu Việt Nam (`numbers_vn.py`)

| Input | Kết quả | Ghi chú |
|---|---|---|
| `1.192` | 1192 | Phân cách hàng nghìn |
| `53,4` | 53.4 | Thập phân |
| `1.192.344.137` | 1192344137 | |
| `(415.884)` | −415884 | Số âm kiểu kế toán |
| `-` (trong ô số) | 0 | `raw='-'` |
| `7100` | 7100 | Không phân cách (finding #18) |
| `+18,36%` | 18.36, `%` | |
| `18,2% N/N` | 18.2, `%`, `basis=YoY`, `direction=unknown` | Finding #10 |
| `~3,0%` | 3.0, `approx=true` | |

Đơn vị: `đồng` (1), `triệu đồng` (10⁶), `tỷ đồng` (10⁹), `nghìn tỷ đồng` (10¹²), `%`, `điểm %`, `lần`, `triệu khách hàng`… Có **property test**: `format_vn(parse_vn(x)) == x` trên mọi số trong bảng `facts`.

### 5.8 Glossary

- Parse tr. 386–387: 6 bảng con × (Thuật ngữ, Định nghĩa), ghép dòng tiếp nối (định nghĩa nhiều dòng có ô "Thuật ngữ" rỗng).
- Thêm alias tay vào `config/glossary_extra.json` cho những cặp mà bảng viết tắt không có, vd. `N/N → so với cùng kỳ năm trước`, `TM → thuyết minh`.
- Khi truy vấn: chỉ mở rộng **query sparse (BM25)** và `lookup_fact`. Không mở rộng query dense.
- **Glossary cũng là nguồn trả lời, không chỉ để mở rộng query** (sq-08, sq-09: *"Theo danh mục thuật ngữ viết tắt…"*). Mỗi mục là một chunk riêng, `content_type=glossary`, với **trang in chính xác của từng mục** (CASA ở tr. 386, RBG ở tr. 387: cùng một trang PDF nhưng khác nửa). Câu hỏi có cụm "viết tắt", "là gì", "thuật ngữ" thì ưu tiên `content_type=glossary`.

### 5.9 Query rewriter

Output: `{"standalone_query", "period", "metric", "entity", "needs_comparison", "needs_calc", "is_forecast"}`. Giữ `metric`, `entity` và `period` của lượt trước để xử lý "còn năm trước thì sao?" → cùng `metric`/`entity`, `period = period − 1`.

**Period guard (deterministic, chạy trước retrieval):** lúc ingest, thu tập các năm thực sự xuất hiện trong tài liệu (`manifest.periods_seen`). Câu hỏi có `period` nằm ngoài tập này (vd. 2027, finding #22), hoặc `is_forecast=true` với một kỳ mà tài liệu không có kế hoạch hay mục tiêu, thì **từ chối sớm** kèm lý do: *"Báo cáo thường niên 2025 không có số liệu/dự báo cho năm 2027."* Không gọi LLM sinh câu trả lời, nên vừa rẻ vừa không thể bịa. Lưu ý: tài liệu **có** kế hoạch 2026 (vd. "Trọng tâm năm 2026"), nên "dự báo 2026" phải đi qua pipeline bình thường chứ không bị chặn.

### 5.10 Hybrid retriever

**Qdrant collection `chunks`** (collection `facts` cấu hình tương tự):

| Thành phần | Cấu hình |
|---|---|
| Named vector `dense` | bge-m3, 1024 chiều, cosine, HNSW (`m=16`, `ef_construct=128`), on-disk payload |
| Named sparse vector `bm25` | **Tự tokenize tiếng Việt** (âm tiết + bigram, giữ nguyên mã như `B05/TCTD-HN`, `CASA`), gửi term-frequency đã bão hòa BM25 (k1=1,2, b=0,75), **`modifier=IDF`** để Qdrant tự tính IDF |
| Payload | `doc_id`, `chunk_id`, `printed_pages[]`, `chapter`, `statement`, `note_no`, `content_type`, `unit`, `text` |
| Payload index | `doc_id` (keyword), `content_type` (keyword), `statement` (keyword), `chapter` (keyword), `printed_pages` (integer) |

> Không dùng `fastembed` BM25 có sẵn vì tokenizer/stemmer của nó viết cho tiếng Anh. Tokenizer nằm trong `core/retrieval/tokenize_vi.py` để query và index dùng **chung một hàm**.

**Truy vấn:** một lần gọi Qdrant Query API:
```python
client.query_points(
    collection_name="chunks",
    prefetch=[
        Prefetch(query=dense_vec,  using="dense", limit=30, filter=f),
        Prefetch(query=sparse_vec, using="bm25",  limit=30, filter=f),
    ],
    query=FusionQuery(fusion=Fusion.RRF),
    limit=8, with_payload=True,
)
```
- `filter f`: luôn có `doc_id`. Nếu `needs_calc` hoặc câu hỏi nhắc chỉ tiêu BCTC thì chạy thêm một nhánh lọc `content_type=table`, đồng thời gọi `lookup_fact`.
- **Score gate** dựa trên score dense của top-1 và số nhánh cùng trả về top-1. Ngưỡng hiệu chỉnh trên eval set.
- Reranker (bge-reranker-v2-m3) là bước có thể thêm sau, chỉ khi eval cho thấy `R-miss` cao.
- **Đã kiểm chứng:** Qdrant embedded (`qdrant-client` 1.19.1) hỗ trợ đủ named dense, sparse `modifier=IDF`, prefetch có filter và `Fusion.RRF`. Cùng một đoạn code chạy cho cả hai chế độ.

### 5.11 Generator

**System prompt (tóm tắt, lưu tại `answering/prompts/generator.md`):**
- Chỉ dùng thông tin trong context và kết quả tool. Trả lời bằng tiếng Việt, ngắn gọn, sẵn để paste vào email.
- Số liệu BCTC thì ưu tiên gọi `lookup_fact`. Mỗi claim phải tham chiếu `chunk_id` **hoặc** `fact_id`.
- Giữ nguyên con số và đơn vị như nguồn. **Không tự đổi đơn vị**; cần đổi thì gọi `convert`.
- **Không tự làm phép tính**; cần tính thì gọi `growth` / `ratio` / `diff`.
- **Không suy ra tăng hay giảm từ một con số % đứng riêng.**
- Không tìm thấy thì trả `status: "not_found"`. Nguồn khác nhau thì trả cả hai và đặt `conflict`.

**Output (Pydantic-validated JSON):**
```json
{
  "status": "answered | not_found | partial",
  "claims": [
    {
      "text": "Tổng tài sản hợp nhất tại 31/12/2025 là 1.192.344.137 triệu đồng",
      "source": {"type": "fact", "id": "p149R_t01_r30_c2"},
      "evidence": "TỔNG TÀI SẢN | 1.192.344.137",
      "numbers": ["1.192.344.137 triệu đồng"]
    }
  ],
  "conflict": {"kind": "rounding | definition | genuine | null", "note": ""}
}
```
JSON sai schema thì retry một lần với thông báo lỗi. Sai lần thứ hai thì từ chối và ghi trace.

### 5.12 Verifier

1. `chunk_id` / `fact_id` có tồn tại và nằm trong context hay kết quả tool không?
2. Claim tham chiếu `chunk_id`: `evidence` phải là substring của chunk text.
3. Mọi số trong claim phải khớp **giá trị và đơn vị** với một số trong evidence hoặc fact (so sánh `value_vnd`, sai lệch làm tròn ≤ 0,05 đơn vị hiển thị). Số do tool tính thì kiểm tra lại bằng cách tính lại.
4. Từ chỉ chiều ("tăng", "giảm") trong claim phải khớp dấu của `diff` hoặc văn xuôi nguồn. Chỉ có KPI `direction=unknown` thì loại từ chỉ chiều.
5. Citation = `printed_pages` từ metadata.

### 5.13 Chính sách khi nguồn khác nhau

| Loại | Nhận diện | Hành vi |
|---|---|---|
| **Làm tròn** | `|a−b| / max(a, b)` < 0,5% sau khi quy đổi unit | **Dẫn bằng số công bố ở phần tổng quan** (đúng con số analyst và gold dùng, vd. "1.192 nghìn tỷ đồng" [tr. 5]), rồi bổ sung số kiểm toán chính xác ("1.192.344.137 triệu đồng" [tr. 297]). Cite cả hai |
| **Khác định nghĩa** | Nhãn khác nhau (vd. "Dư nợ tín dụng" theo NHNN so với "Cho vay khách hàng"), hoặc dòng cha so với dòng con | Trả số khớp đúng thuật ngữ user hỏi. Nếu user hỏi mơ hồ ("dư nợ") thì nêu cả hai, mỗi số kèm định nghĩa và citation |
| **Khác thật sự** | Còn lại | Nêu cả hai, gắn cờ "cần kiểm tra", không chọn hộ |

> Đã có ví dụ thật cho cả ba loại (findings #9, #14, #13). Nên đưa vào eval set và vào video demo.

### 5.14 Ảnh

- Lọc: ảnh lặp > 2 lần (logo, nền), ảnh phủ > 60% trang (full-bleed), ảnh < 1% trang (icon) → `decorative`.
- Còn lại khoảng 40 ảnh mid-size: duyệt tay một lần bằng contact sheet, gắn nhãn `informative` hoặc `decorative` vào `config/images.json`. Ghi thời gian bỏ ra.
- Ảnh `informative` (nếu có): mô tả bằng VLM **một lần lúc ingest**, lưu thành chunk `content_type=figure` có cite trang. Chi phí ghi vào ingest cost.
- Lý do không làm tự động hoàn toàn: OCR số không tìm được ảnh nào mang số liệu (finding #16). Một classifier cho 40 ảnh không đáng công so với duyệt tay ~10 phút. **Với 1.000 tài liệu** thì cần classifier (CLIP zero-shot hoặc VLM rẻ), ghi vào phần scale.

---

## 6. Tech stack

| Tầng | Lựa chọn | Lý do (có số đo từ M0) | Phương án thay thế |
|---|---|---|---|
| Env | Python 3.11, `uv` | Tái lập bằng `uv.lock` | pip |
| PDF text, layout, bảng | **PyMuPDF ≥ 1.24** (`find_tables`, `get_text("dict")`, `get_drawings`) | Đủ cột 2024 ở chỗ pdfplumber trả `None`, độ phủ BCTC 98,6%, có cờ superscript và tọa độ | pdfplumber (để debug) · Docling (chỉ benchmark cho bảng vắt gutter nếu còn giờ) |
| Fallback bảng | Gom word theo tọa độ (tự viết, ~80 dòng) | Cho các nửa trang có độ phủ < 95% | Camelot stream |
| OCR | Không dùng cho text (finding #15) | Text layer sạch | tesseract `vie` cho ảnh nếu cần |
| Ảnh informative | VLM qua LiteLLM (một lần, tùy chọn) | Ít ảnh | Bỏ qua, ghi vào SUBMISSION |
| **Vector DB** | **Qdrant** (server qua Docker · embedded `QdrantClient(path=…)` khi chấm bài) | Hybrid dense + sparse và RRF **phía server** trong 1 lần gọi; sparse có `modifier=IDF` thay cho thư viện BM25 riêng; lọc payload (`doc_id`, `content_type`…); HNSW; cùng một client cho cả hai chế độ; có snapshot/backup | pgvector (gộp vào Postgres nhưng không có sparse/hybrid sẵn) · Weaviate · Milvus |
| **SQL DB** | **PostgreSQL 16** (production) · SQLite (chấm bài), qua **SQLAlchemy 2.0 + Alembic** | Facts (NUMERIC chính xác), sessions, index_versions; migration có version | — |
| Số học | `decimal.Decimal` | Không lỗi float | |
| Embedding | **BAAI/bge-m3** local | Tiếng Việt tốt, offline | multilingual-e5-large · OpenAI |
| LLM gateway | **LiteLLM** | Đổi provider bằng env var | SDK trực tiếp |
| Structured output | Pydantic v2 | Validate JSON claims | |
| Eval | **RAGAS** (pin version) + script tự viết + chấm tay | Xem §10 | DeepEval |
| Trace | JSONL + `trace_id` xuyên suốt CLI/API | | Langfuse |

**Lớp ứng dụng**

| Tầng | Lựa chọn | Lý do | Thay thế |
|---|---|---|---|
| Python workspace | **uv workspace** (core, api, cli là các package riêng, chung một `uv.lock`) | Ranh giới phụ thuộc rõ ràng, một lệnh `uv sync` | Poetry |
| Config | `pydantic-settings` | Đọc env và validate kiểu một chỗ | |
| API | **FastAPI** + Uvicorn, SSE qua `sse-starlette` | OpenAPI tự sinh, async, Pydantic dùng chung với core | Litestar |
| Session store | Bảng `sessions`, `messages` trong SQL DB | Một DB cho mọi state | Redis (khi cần TTL hoặc nhiều instance) |
| Logging | `structlog` (JSON) | Log và trace cùng `trace_id` | stdlib logging |
| Render trang | PyMuPDF → PNG (clip nửa spread) + cache đĩa | Trang in chính xác, tô sáng bbox | pdf.js ở client |
| CLI | `typer` + `prompt_toolkit` + `rich` | Subcommand `chat`, `batch`, `ingest`, `eval` | argparse |
| Web | **Next.js 15 (App Router) + TypeScript** | | Vite + React |
| UI components | Tailwind + **shadcn/ui** (dùng nguyên, không tự xây design system) | Nhanh, không bị coi là design system | Mantine |
| Data fetching | TanStack Query + `EventSource` cho SSE | | SWR |
| API types | `openapi-typescript` sinh từ `/openapi.json` | Không lệch contract | Viết tay |
| JS package manager | pnpm | | npm |
| Lint/format | `ruff` + `mypy` (Python) · `eslint` + `prettier` (TS) · `pre-commit` | | |
| Test | `pytest` + `hypothesis` · `httpx` TestClient cho API · Vitest + Playwright (1–2 luồng e2e cho web) | | |
| Dev runtime | `Makefile` + `docker-compose.yml` (qdrant, postgres, api, web; **chạy local**, không phải deploy) | Một lệnh dựng toàn bộ stack production | `honcho` / Procfile |

| Artefact | Parquet (`pyarrow`) cho vector, JSONL cho chunk/fact | Trung lập với DB, nạp vào được mọi chế độ | — |

**Cố ý không dùng:** LangChain/LlamaIndex (cần giải thích được từng dòng), Kubernetes, CI/CD, auth.

---

## 7. Cấu hình (environment variables)

| Biến | Bắt buộc | Mặc định | Mô tả |
|---|---|---|---|
| `LLM_MODEL` | ✅ | — | Cú pháp LiteLLM: `openai/…`, `anthropic/…`, `gemini/…`, `ollama/qwen2.5:14b` |
| `LLM_MODEL_SMALL` | | = `LLM_MODEL` | Rewriter |
| `JUDGE_MODEL` | | — | Model cho RAGAS, **nên khác** `LLM_MODEL` |
| `VLM_MODEL` | | — | Mô tả ảnh lúc ingest (tùy chọn) |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | Tùy provider | — | |
| `OLLAMA_API_BASE` | Nếu local | `http://localhost:11434` | |
| `EMBED_MODEL` | | `BAAI/bge-m3` | Phải khớp `index/manifest.json` |
| `EMBED_DEVICE` | | `cpu` | `cpu` / `cuda` / `mps` |
| `INDEX_DIR` | | `./index` | |
| `TOP_K` | | `8` | |
| `REFUSAL_THRESHOLD` | | từ eval | |
| `TRACE_DIR` | | `./traces` | |
| `LLM_PRICE_IN` / `LLM_PRICE_OUT` | | — | USD / 1M token |
| `APP_ENV` | | `dev` | `dev` bật `/v1/traces`, log chi tiết |
| `API_HOST` / `API_PORT` | | `127.0.0.1` / `8000` | |
| `CORS_ORIGINS` | | `http://localhost:3000` | |
| `DATABASE_URL` | | `sqlite:///./var/app.db` | Production: `postgresql+psycopg://ircb:ircb@localhost:5432/ircb` |
| `QDRANT_URL` | | — | Đặt (vd. `http://localhost:6333`) thì dùng **Qdrant server** |
| `QDRANT_PATH` | | `./var/qdrant` | Dùng khi **không** có `QDRANT_URL` → Qdrant embedded |
| `QDRANT_API_KEY` | | — | Nếu server bật API key |
| `QDRANT_COLLECTION_PREFIX` | | `ircb_` | → `ircb_chunks`, `ircb_facts` |
| `AUTO_LOAD_INDEX` | | `true` | Tự nạp artefact vào DB nếu thiếu/lệch version |
| `PAGE_CACHE_DIR` | | `./var/page_cache` | PNG trang in đã render |
| `PDF_PATH` | | `./data/techcombank-…pdf` | Cần cho render trang. Thiếu thì web chỉ hiện text bằng chứng |
| `NEXT_PUBLIC_API_URL` | | `http://localhost:8000` | Biến của web (`apps/web/.env.local`) |

---

## 8. Cấu trúc repository

Monorepo, chia theo **packages** (thư viện, không chạy độc lập) và **apps** (thứ chạy được).

```
.
├── README.md                       # quickstart: prerequisites + 1 lệnh
├── SUBMISSION.md                   # điền từ docs/SUBMISSION_TEMPLATE.md, giữ nguyên heading
├── Makefile                        # setup · up · chat · batch · eval · ingest · test · lint · gen-types
├── docker-compose.yml              # qdrant + postgres + api + web (chạy local, không phải deploy)
├── pyproject.toml                  # uv workspace root + cấu hình ruff/mypy/pytest
├── uv.lock
├── .env.example                    # toàn bộ biến ở §7
├── .pre-commit-config.yaml
├── .importlinter                   # luật: core không import apps
│
├── docs/
│   ├── DESIGN.md                   # tài liệu này
│   ├── worklog.md                  # nhật ký thử nghiệm → nguồn cho "What I tried that did not work"
│   ├── adr/                        # 1 file / quyết định lớn (D1–D13 ở §14)
│   │   ├── 0001-half-page-unit.md
│   │   └── ...
│   ├── api.md                      # mô tả endpoint + ví dụ SSE
│   ├── m0-findings.md              # bản dài của §2 + ảnh minh họa
│   ├── m0_report.json              # output của scripts/profile_pdf.py
│   └── SUBMISSION_TEMPLATE.md      # bản gốc của đề, để đối chiếu heading
│
├── packages/
│   └── core/                       # ── thư viện Python `ircb` ──
│       ├── pyproject.toml          # deps: pymupdf, qdrant-client, sqlalchemy, sentence-transformers, litellm, pyarrow, pydantic…
│       ├── src/ircb/
│       │   ├── __init__.py
│       │   ├── settings.py         # pydantic-settings, đọc env
│       │   ├── domain/             # kiểu dữ liệu thuần, không I/O
│       │   │   ├── models.py       # Chunk, Fact, Claim, Answer, Citation, Turn
│       │   │   ├── numbers_vn.py   # parse/format số VN
│       │   │   └── units.py        # thang đơn vị, quy đổi
│       │   ├── ingestion/
│       │   │   ├── spread.py       # tách nửa trang + page map + verify
│       │   │   ├── layout.py       # span/word, furniture, superscript
│       │   │   ├── tables.py       # find_tables, header nhiều tầng, row_level, gutter
│       │   │   ├── table_qa.py     # độ phủ + fallback tọa độ
│       │   │   ├── kpi.py · prose.py · glossary.py · images.py
│       │   │   ├── facts.py        # → facts.jsonl
│       │   │   ├── chunking.py
│       │   │   └── pipeline.py     # build_index(): điều phối + ingest_report + manifest
│       │   ├── storage/            # mọi I/O với DB nằm ở đây
│       │   │   ├── db.py           # engine/session SQLAlchemy từ DATABASE_URL
│       │   │   ├── models.py       # ORM: Fact, Document, IndexVersion, Session, Message
│       │   │   ├── migrations/     # Alembic (env.py, versions/)
│       │   │   ├── vector_store.py # QdrantStore: tạo collection, upsert, hybrid query (server | embedded)
│       │   │   ├── fact_repo.py    # FactRepository: Qdrant search → SQL fetch
│       │   │   ├── session_repo.py
│       │   │   ├── artefacts.py    # đọc/ghi index/ (jsonl, parquet, manifest)
│       │   │   ├── loader.py       # `index load`: artefact → Qdrant + SQL, idempotent
│       │   │   └── page_store.py   # PageRenderer: render PNG nửa trang + highlight + cache
│       │   ├── retrieval/
│       │   │   ├── tokenize_vi.py · embed.py · sparse_bm25.py · hybrid.py · gate.py
│       │   │   └── glossary_expand.py
│       │   ├── answering/
│       │   │   ├── rewriter.py
│       │   │   ├── generator.py
│       │   │   ├── tools.py        # lookup_fact, growth, ratio, diff, convert
│       │   │   ├── verifier.py
│       │   │   ├── renderer.py     # claims → text tiếng Việt + [tr. N]
│       │   │   └── prompts/        # prompt dạng file .md, có version
│       │   ├── llm/
│       │   │   └── client.py       # wrapper LiteLLM: retry, timeout, đếm token, tính cost
│       │   ├── observability/
│       │   │   ├── tracing.py      # Trace context, ghi JSONL
│       │   │   └── logging.py      # structlog
│       │   └── service.py          # AnswerService.ask(history, message) → Answer  ⬅ điểm vào duy nhất
│       └── tests/
│           ├── unit/               # numbers_vn (+hypothesis), units, verifier, tools
│           ├── golden/             # page map 190/190, bảng tr. 297/337/374–375, KPI tr. 5/48
│           └── fixtures/
│
├── apps/
│   ├── api/                        # ── FastAPI ──
│   │   ├── pyproject.toml          # deps: ircb-core, fastapi, uvicorn, sse-starlette
│   │   ├── src/ircb_api/
│   │   │   ├── main.py             # create_app(), lifespan load index một lần
│   │   │   ├── deps.py             # DI: AnswerService, SessionRepo, PageRenderer
│   │   │   ├── routers/
│   │   │   │   ├── chat.py         # POST /v1/chat (SSE)
│   │   │   │   ├── sessions.py
│   │   │   │   ├── pages.py        # GET /v1/pages/{printed}/image
│   │   │   │   ├── facts.py
│   │   │   │   ├── traces.py       # chỉ dev
│   │   │   │   └── health.py
│   │   │   ├── schemas.py          # DTO request/response (map từ domain models)
│   │   │   └── errors.py           # exception handler, mã lỗi thống nhất
│   │   └── tests/                  # httpx TestClient, contract test SSE
│   │
│   ├── cli/                        # ── Typer: kênh chấm bài ──
│   │   ├── pyproject.toml
│   │   └── src/ircb_cli/
│   │       ├── main.py             # `ircb chat | batch | ingest | eval | profile`
│   │       ├── repl.py
│   │       └── batch.py            # JSON/JSONL vào → JSONL ra (answer, citations, latency, cost, trace_id)
│   │
│   └── web/                        # ── Next.js ──
│       ├── package.json · pnpm-lock.yaml · tsconfig.json · next.config.ts
│       ├── .env.local.example      # NEXT_PUBLIC_API_URL
│       ├── src/
│       │   ├── app/
│       │   │   ├── layout.tsx
│       │   │   ├── page.tsx                    # màn chat
│       │   │   └── sessions/[id]/page.tsx
│       │   ├── components/
│       │   │   ├── chat/                       # MessageList, Composer, StatusStream
│       │   │   ├── answer/                     # AnswerCard, CitationChip, ConflictNote, RefusalCard, CopyButton
│       │   │   ├── evidence/                   # PageViewer (ảnh trang + highlight), EvidencePanel
│       │   │   └── ui/                         # shadcn (sinh tự động, không sửa tay)
│       │   ├── lib/
│       │   │   ├── api/client.ts               # fetch + SSE wrapper
│       │   │   ├── api/types.gen.ts            # sinh từ OpenAPI (`make gen-types`)
│       │   │   └── format.ts                   # chỉ hiển thị, không tính toán số liệu
│       │   └── hooks/useChat.ts
│       └── tests/                              # Vitest (component) + Playwright (e2e: hỏi → bấm [tr. N] → thấy trang)
│
├── eval/                           # đánh giá, tách khỏi apps
│   ├── datasets/
│   │   ├── own_questions.jsonl     # gold_pages, gold_value, gold_unit, type
│   │   └── adversarial.jsonl       # câu trả lời cố ý sai đơn vị/chiều để kiểm định judge
│   ├── runners/
│   │   ├── run_eval.py             # retrieval metrics + verifier stats + xuất sheet chấm tay
│   │   ├── ragas_eval.py
│   │   └── judge_agreement.py      # Cohen's κ RAGAS vs người chấm
│   ├── scoring/score_sheet.csv
│   └── reports/                    # kết quả từng lần chạy (có commit hash)
│
├── config/                         # cấu hình riêng cho tài liệu này (dữ liệu, không phải code)
│   ├── sections.json · page_overrides.json · glossary_extra.json · images.json
│
├── data/                           # file của đề, giữ đúng đường dẫn đề dùng, không sửa
│   ├── techcombank-bao-cao-thuong-nien-2025-vie-update.pdf
│   └── sample_questions.json
├── index/                          # ⬅ SHIP: artefact đã build
│   ├── manifest.json               # index_version, hash PDF, EMBED_MODEL, tokenizer version, số point
│   ├── page_map.json · chunks.jsonl · facts.jsonl · glossary.json
│   ├── vectors.parquet             # chunk/fact_id, dense[1024], sparse(indices, values)
│   └── ingest_report.json
│
├── scripts/
│   ├── profile_pdf.py              # khảo sát M0
│   ├── fetch_index.sh              # tải index nếu không nằm trong repo
│   └── smoke_test.sh               # máy sạch: setup → batch 10 câu → so số dòng output
│
├── infra/
│   └── docker/
│       ├── api.Dockerfile
│       └── web.Dockerfile
│
└── var/                            # runtime, gitignore: app.db, qdrant/ (embedded), page_cache/, traces/
```

**Vì sao chia như vậy**

| Quyết định | Lý do |
|---|---|
| `packages/core` tách khỏi `apps/*` | CLI chấm bài và web dùng **chung một** `AnswerService`, nên kết quả eval trên CLI cũng đúng cho web. Đổi framework web không đụng tới logic |
| `domain/` không có I/O | `numbers_vn`, `units` và models test được thuần túy, nhanh, dùng được cho property test |
| `storage/` riêng | Chỉ chỗ này biết Qdrant, SQL và artefact. Đổi DB hay chế độ chạy không đụng tới retrieval/answering |
| Artefact ≠ DB | Index ship được, diff được, nạp được vào mọi môi trường; DB có thể xóa đi dựng lại bất cứ lúc nào |
| `prompts/` là file | Diff được, gắn version vào trace, giải thích được trong walkthrough |
| `eval/` ngang hàng với `apps/` | Eval là sản phẩm của bài, không phải test phụ |
| `config/` khác `settings.py` | `config/` là dữ liệu đặc thù tài liệu (đổi khi đổi PDF). `settings.py` là cấu hình môi trường (đổi khi đổi máy hay provider) |
| `var/` | Mọi thứ sinh ra lúc chạy nằm một chỗ, xóa được an toàn |

---

## 9. Cách chạy

**Chế độ 1: chấm bài (chỉ cần Python, không Docker).** Qdrant embedded + SQLite.
```bash
# Prerequisites: Python 3.11, uv, ~3 GB disk (bge-m3), RAM ≥ 8 GB
make setup                       # = uv sync + cp .env.example .env
# điền LLM_MODEL + API key trong .env (để trống QDRANT_URL, giữ DATABASE_URL mặc định)

uv run ircb chat                 # lần đầu tự `index load` (~vài giây) vào var/qdrant + var/app.db
uv run ircb batch data/sample_questions.json --out eval/reports/run.jsonl
uv run ircb eval --dataset eval/datasets/own_questions.jsonl
```

**Chế độ 2: production local (Docker).** Qdrant server + PostgreSQL + API + web.
```bash
make up                          # docker compose up: qdrant :6333 · postgres :5432 · api :8000 · web :3000
                                 # api khởi động → alembic upgrade head → auto `index load` nếu lệch version
make logs · make down
```

`docker-compose.yml` (rút gọn):
```yaml
services:
  qdrant:   { image: "qdrant/qdrant:vX.Y.Z",   # pin cùng minor với qdrant-client trong uv.lock volumes: [qdrant_data:/qdrant/storage], ports: ["6333:6333"],
              healthcheck: { test: ["CMD", "wget", "-qO-", "localhost:6333/readyz"] } }
  postgres: { image: postgres:16, environment: { POSTGRES_USER: ircb, POSTGRES_PASSWORD: ircb, POSTGRES_DB: ircb },
              volumes: [pg_data:/var/lib/postgresql/data] }
  api:      { build: { dockerfile: infra/docker/api.Dockerfile }, env_file: .env,
              environment: { QDRANT_URL: "http://qdrant:6333", DATABASE_URL: "postgresql+psycopg://ircb:ircb@postgres:5432/ircb" },
              volumes: ["./index:/app/index:ro", "./data:/app/data:ro"], depends_on: [qdrant, postgres] }
  web:      { build: { dockerfile: infra/docker/web.Dockerfile }, environment: { NEXT_PUBLIC_API_URL: "http://localhost:8000" } }
volumes: { qdrant_data: {}, pg_data: {} }
```
> Pin chính xác version image. Server và `qdrant-client` nên cùng minor version để tránh cảnh báo tương thích.

**Không Docker nhưng vẫn muốn web:**
```bash
make api                         # uv run uvicorn ircb_api.main:app --reload (dùng chế độ 1)
make web                         # pnpm --dir apps/web dev
make gen-types                   # sinh lại TS types khi API đổi
```

**Phát triển:**
```bash
make test                        # pytest core + api (SQLite + Qdrant embedded), vitest web
make test-integration            # chạy lại test storage với Qdrant server + Postgres (docker)
make lint                        # ruff, mypy, import-linter, eslint
uv run ircb profile data/<pdf>   # khảo sát M0
uv run ircb ingest data/<pdf>    # build lại artefact index/ (không cần cho chấm bài)
uv run ircb index load [--force] # nạp artefact vào Qdrant + SQL
uv run alembic -c packages/core/alembic.ini upgrade head
```

---

## 10. Đánh giá

### 10.0 Phân tích 10 câu mẫu

| ID | Loại | Trang gold | Vùng (§2.1) | Thành phần cần có | Bẫy |
|---|---|---|---|---|---|
| sq-01 | company_profile | 4 | Bìa/điểm nhấn: văn xuôi | prose chunk | "29 trên 34": hai số đi liền nhau |
| sq-02 | company_profile | 4 | văn xuôi | prose chunk | Hai tổ chức, hai mức (BB và **BB-**), hai triển vọng: dễ trả thiếu |
| sq-03 | key_figures | 5 | Ô KPI | **KPI parser** | Có số kiểm toán 1.192.344.137 triệu ở tr. 297 → chính sách làm tròn (§5.13) |
| sq-04 | key_figures | 5 | Ô KPI | KPI parser | Có thể nhầm "CASA" trong văn xuôi tr. 49 có chú thích |
| sq-05 | key_figures | 5 | Ô KPI | KPI parser | Gold kèm mô tả của ô ("nhóm tốt nhất…") |
| sq-06 | key_figures | 5 | Ô KPI | KPI parser | **Câu hỏi kép**: giá trị + CAGR 16,5%. Ô bên cạnh có CAGR 17,3%, ghép sai ô là sai số |
| sq-07 | segment_performance | 59 | Ô KPI chương RBG | KPI parser + **mũi tên** + ngữ cảnh khối | Stream order bị trộn (finding #19); gold có "tăng" (finding #20); phải biết đây là khối Bán lẻ |
| sq-08 | terminology | 387 | Viết tắt | **glossary chunk** | Trang đúng là nửa phải của PDF 194 |
| sq-09 | terminology | 386 | Viết tắt | glossary chunk | Nửa trái. Retrieval dễ kéo về văn xuôi nói về CASA thay vì bảng thuật ngữ |
| sq-10 | unanswerable | — | — | **period guard** | Tài liệu có kế hoạch **2026** → model dễ đem ra trả lời cho 2027 |

**Kết luận cho thiết kế:**
- 6/10 câu phụ thuộc KPI parser, 2/10 phụ thuộc glossary chunk. Cả hai đều là bắt buộc, không phải phần làm thêm.
- **Không có câu nào về BCTC, tính toán hay đa lượt**, nhưng đó lại là phần nặng nhất của thiết kế và nhiều khả năng chiếm phần lớn bộ câu ẩn (finding #21).
- Không được thêm luật đặc biệt kiểu "câu hỏi tổng tài sản thì đọc tr. 5". Mọi cải tiến phải đo được trên eval set riêng, không chỉ trên 10 câu.

### 10.0.1 Định dạng dataset và cách chấm

Eval set riêng dùng **đúng schema của đề** (`id`, `category`, `question`, `gold_answer`, `gold_printed_pages`, `answerable`), thêm các trường tùy chọn: `turns` (cho câu đa lượt), `gold_values` (`[{"value": "328,1", "unit": "nghìn tỷ đồng"}]`), `direction`.

| Tiêu chí | Cách chấm | Tự động? |
|---|---|---|
| **Answer correct** | Đúng / Một phần / Sai. "Một phần" = thiếu một vế của câu hỏi kép (sq-02, sq-06) hoặc thiếu chiều tăng/giảm | Chấm tay, script gợi ý bằng cách so `gold_values` |
| **Citation hit** | Mọi trang trong `gold_printed_pages` đều có trong citation | Tự động |
| **Citation precision** | Mọi trang được cite thực sự chứa claim (verifier + kiểm tra ngẫu nhiên bằng tay) | Bán tự động |
| **Refusal** | `answerable=false` → phải từ chối; `answerable=true` → không được từ chối | Tự động |
| **Unit/scale** | Số + đơn vị khớp `gold_values` sau quy đổi | Tự động |

Báo cáo điểm theo **từng tiêu chí và từng category**, không gộp thành một con số duy nhất.

### 10.1 Bốn lớp

| Lớp | Công cụ | Vai trò |
|---|---|---|
| **Ingestion** | `ingest_report.json` + golden test | Page map 100%, độ phủ bảng, fact golden (khoảng 30 ô kiểm tra tay trên tr. 297, 337, 374–375, 5, 14) |
| Retrieval | Recall@K, MRR theo `gold_pages` | Nguồn sự thật cho `R-miss` |
| Citation, số liệu | Verifier + so `gold_value`/`gold_unit` | Bắt lỗi đơn vị và sai trang |
| Correctness, refusal | **Chấm tay** | Ground truth |
| Tín hiệu tự động | **RAGAS**: faithfulness, context precision/recall, factual correctness | Regression khi đổi prompt hay model |

### 10.2 Kiểm định RAGAS (bắt buộc trước khi báo cáo điểm RAGAS)

1. Chấm tay ~40 câu (nhãn: đúng / một phần / sai).
2. Chạy RAGAS với `JUDGE_MODEL` khác `LLM_MODEL`.
3. Báo cáo agreement % và Cohen's κ giữa RAGAS (đặt ngưỡng) và người chấm.
4. **Bộ test đối nghịch:** 10 câu trả lời cố ý sai đơn vị (nghìn tỷ ↔ tỷ, triệu ↔ tỷ), sai dòng cha/con, sai chiều tăng/giảm. Đếm số câu RAGAS bắt được. Đây là phần cho thấy *vì sao* verifier deterministic vẫn cần thiết.
5. Câu ngoài phạm vi chấm riêng (refusal precision/recall), không đưa qua RAGAS.

### 10.3 Phân loại lỗi

`I-extract` (fact hoặc chunk sai ngay từ ingest) · `R-miss` · `G-wrong` · `G-overrefuse` · `V-blocked` · `Hallucination-leak`. Nhãn **`I-extract` mới** là để trả lời câu "lỗi ở đâu", vì đề hỏi retrieval hay generation, nhưng với tài liệu này còn lỗi ở bước trích xuất.

### 10.4 Eval set riêng (~40 câu, ưu tiên phủ những gì 10 câu mẫu không có)

| Category | Số câu | Ví dụ từ tài liệu thật |
|---|---|---|
| key_figures (KPI) | 4 | LNTT 32,5 nghìn tỷ, tăng 18,2% [tr. 48] |
| segment_performance | 4 | Số dư tiền gửi RBG 475,8 nghìn tỷ [tr. 59]; LNTT TCBS 7.109 tỷ [tr. 77] |
| **direction** | 2 | CIR TCBS năm 2025 **giảm** 0,5% [tr. 81] |
| **financial_statements** (ô bảng BCTC) | 8 | CK đầu tư sẵn sàng để bán 31/12/2024 [tr. 337] |
| parent_child_rows | 3 | Cho vay khách hàng: thuần hay gộp [tr. 297] |
| gutter_table | 2 | Khoản mục ở tr. 374–375 |
| definition_or_rounding | 4 | Dư nợ tín dụng vs cho vay KH [tr. 14 / 48 / 297] |
| **multi_turn** | 5 cặp | "Tổng tài sản 2025?" → "còn năm trước thì sao?" (978.799 tỷ [tr. 14]) |
| **calculation** | 4 | Tăng trưởng tổng tài sản tính từ fact, đối chiếu 21,82% [tr. 14] |
| terminology | 3 | CIBG, N/N, TCBS |
| narrative | 3 | Trọng tâm 2026 |
| unanswerable | 6 | Giá cổ phiếu hôm nay · số liệu ngân hàng khác · BCTC riêng lẻ · dự báo 2028 · **"kế hoạch LNTT 2026"** (cần kiểm tra tài liệu có số này không, đây là câu ranh giới) |

> Các ví dụ ở trên lấy từ trang đã xem trong M0. **Gold của eval set riêng phải được đối chiếu tay với PDF**, không được lấy từ output của hệ thống.

Viết eval set **trước khi** tối ưu prompt. Không chỉnh theo từng câu mẫu.

### 10.5 Ánh xạ SUBMISSION.md (giữ nguyên heading của template)

| Heading của template | Nguồn trong dự án | Bằng chứng cần có |
|---|---|---|
| How to run · Clean machine | §9 Chế độ 1 | `scripts/smoke_test.sh` chạy trên venv sạch, ghi lại output |
| How to run · Different key or local model | §7 | Ví dụ `.env` cho OpenAI, Anthropic, Ollama |
| How to run · Batch run | `ircb batch data/sample_questions.json` | Định dạng JSONL output |
| How to run · Environment variables | §7 (copy nguyên bảng) | — |
| How to run · Shipped index | `index/` + `manifest.json` | Kích thước, `index_version` |
| Depth track(s) chosen | §3.2 | Findings #6–#13, #19–#20 làm lý do |
| Architecture | §4 (sơ đồ) + §5 tóm tắt | — |
| **What I tried that did not work** | Ghi trong lúc làm, không viết bù ở cuối | Đã có: pdfplumber `lines` mất cột 2024; pdfplumber `text` băm chữ; `sort=True` xen kẽ cột; đọc KPI theo stream order bị trộn; OCR ảnh không tìm ra số mới |
| Evaluation | §10.0.1 + kết quả | Bảng theo tiêu chí × category, phương pháp chấm, người chấm, thời gian chấm |
| Cost and latency | §11 | Số đo thật: ingest wall-clock, p50/p95, USD/query |
| What I deliberately did not build | §3.4 | — |
| With 10x time and budget | §11 (scale) + §15 | Theo thứ tự ưu tiên |
| Demo video | M7 | Một take, 10 câu mẫu, có cả câu bị từ chối |

> Nên giữ một file `docs/worklog.md` ghi lại ngay trong lúc làm: đã thử gì, kết quả ra sao, mất bao lâu. Mục "What I tried that did not work" được đọc rất kỹ, và nó chỉ thuyết phục khi có số liệu thật.

---

## 11. Chi phí & hiệu năng

| Hạng mục | Số đo hiện có | Cần đo |
|---|---|---|
| M0 profiling | **~62s CPU** (container cloud, 1 lõi) | — |
| Ingestion | — | Wall-clock từng bước, token VLM (nếu dùng) |
| Query | — | Latency từng bước, token, USD, p50/p95 |

Scale lên 1.000 tài liệu: page map chuyển sang chế độ đọc header/footer tổng quát · Table QA trở thành cổng bắt buộc, tài liệu có độ phủ thấp đưa vào hàng đợi duyệt · Qdrant server có replication và quantization (scalar int8 cho dense), mỗi tài liệu một shard key hoặc lọc `doc_id` · Postgres với partition theo `doc_id` · ingestion thành worker xếp hàng · classifier ảnh · cache truy vấn (Redis) · định tuyến model.

---

## 12. Rủi ro

| Rủi ro | XS | TĐ | Giảm thiểu |
|---|---|---|---|
| Bảng vắt gutter trích sai | TB | Cao | Golden test tr. 374–375, cite 2 trang |
| Dòng cha/con nhầm | Cao | Cao | `row_level` từ x0 + bold, golden test tr. 297 |
| Sai thang đơn vị | TB | Nghiêm trọng | Unit bắt buộc trên fact, verifier so `value_vnd`, test đối nghịch |
| Sai chiều tăng/giảm từ KPI | TB | Cao | `direction=unknown` mặc định, verifier kiểm từ chỉ chiều |
| Header nhiều tầng sai | TB | TB | Forward-fill + golden tr. 14 |
| Fallback tọa độ gán lệch dòng có nhãn nhiều dòng | TB | TB | Gắn số theo dòng *cuối* của nhãn nhiều dòng ("Trong đó: / Trái phiếu…"), có test |
| Ảnh informative bị bỏ sót | Thấp | TB | Duyệt tay ~40 ảnh, ghi vào SUBMISSION |
| Kết quả khác nhau giữa Qdrant embedded và server | Thấp | TB | Embedded duyệt toàn bộ (exact), server dùng HNSW (xấp xỉ). Với ~3k point, đặt `hnsw_ef` cao; `make test-integration` so top-k của hai chế độ trên eval set |
| Người chấm không có Docker | TB | Cao | Chế độ chấm bài không cần Docker; `smoke_test.sh` chạy trên venv sạch |
| Hết thời gian | Cao | TB | Thứ tự cắt giảm ở §13 |

---

## 13. Kế hoạch (~14 giờ cốt lõi + ~4,5 giờ API/web)

| Milestone | Giờ | Nội dung | Điều kiện xong |
|---|---|---|---|
| **M0 Khảo sát** | 1 | ✅ *Đã xong* (§2, §10.0). Còn lại: viết nháp eval set riêng, đối chiếu gold với PDF | Eval set nháp |
| M1a Spread + layout | 1,5 | `spread.py`, `layout.py`, page map test | 190/190 khớp |
| M1b Bảng + fact | 2,5 | `tables.py`, `table_qa.py`, `facts.py`, golden test | Độ phủ ≥ 99%, golden pass |
| M1c KPI + prose + chunk + index | 2 | Artefact `index/`, `QdrantStore`, `loader`, Alembic migration đầu tiên | `ircb index load` chạy được trên cả embedded và server |
| M2 E2E | 1,5 | Retrieve + generate + `lookup_fact` + render | Chạy hết 10 câu, eval v0 |
| M3 Verifier + calc | 1,5 | | Test đối nghịch pass |
| M4 Rewriter + glossary | 1 | | Follow-up chạy được |
| M5 Đo đạc | 1,5 | Chấm tay, RAGAS + kiểm định, cost/latency | Bảng số liệu |
| M6 Đóng gói | 1,5 | README, `.env.example`, batch, SUBMISSION, `smoke_test.sh` | Chạy trên venv sạch |
| M7 Video | 0,5 | | 3–5 phút, một take |
| M8 API | 1,5 | FastAPI: chat SSE, pages, sessions, health + contract test | `make api` chạy, OpenAPI sinh được |
| M9 Web | 3 | Chat, AnswerCard, CitationChip → PageViewer có highlight, nút copy | E2E Playwright: hỏi → bấm `[tr. N]` → thấy đúng trang |

> M0–M7 (~14 giờ) là phần cần cho bài nộp. M8–M9 (~4,5 giờ) chỉ làm **sau khi** M0–M7 xong. Nếu làm web thì quay video demo trên web, nhưng batch vẫn chạy qua CLI.
> **Ghi chú tổ chức code:** dù M8–M9 làm sau, cấu trúc monorepo (§8) dựng ngay từ M1 để không phải refactor.

**Thứ tự cắt giảm:** web (M9) → API (M8) → benchmark embedding → VLM cho ảnh → RAGAS (giữ chấm tay).
**Không cắt:** page map, KPI parser + mũi tên (6/10 câu mẫu phụ thuộc), bảng + fact store, glossary chunk, period guard, verifier, eval trung thực.
**Không cắt:** page map, bảng + fact store, verifier, refusal, eval trung thực.

---

## 14. Decision log

| # | Quyết định | Lý do | Đánh đổi |
|---|---|---|---|
| D1 | Đơn vị xử lý là nửa trang | 196 trang spread | Phải xử lý riêng 6 bảng vắt gutter |
| D2 | Page map theo quy luật + kiểm tra header, fail build khi lệch | Đúng 190/190, deterministic | Quy luật là đặc thù tài liệu, phần kiểm tra là tổng quát |
| D3 | Số trang lấy từ metadata | LLM không thể bịa trang | Model phải trả đúng id |
| D4 | PyMuPDF thay pdfplumber | pdfplumber mất cả cột 2024 | Phụ thuộc AGPL (ghi rõ trong SUBMISSION) |
| D5 | Fact store (SQL) + tool chỉ nhận `fact_id` | Đọc ô và tính toán deterministic | Thêm bước ingest, ~2,5 giờ |
| D6 | Chiều tăng/giảm của KPI đọc từ hình vector, fallback `unknown` | Mũi tên là hình vẽ; gold (sq-07) dùng "tăng"; đã có ví dụ giảm thật (tr. 81) | Phụ thuộc cách vẽ của InDesign; có golden test UP/DOWN |
| D7 | Track chính: Document Intelligence | Rủi ro lớn nhất nằm ở trích xuất (§3.2) | Retrieval làm gọn |
| D8 | Không OCR text, duyệt tay ảnh | Text layer sạch, OCR không tìm thấy số mới | Không tự động khi scale |
| D9 | RAGAS là tín hiệu phụ, phải kiểm định | Judge mù với lỗi đơn vị | Tốn thêm thời gian chấm tay |
| D10 | Không dùng LangChain/LlamaIndex | Giải thích được từng dòng | Tự viết nhiều hơn |
| D11 | Chỉ có BCTC hợp nhất | Tài liệu không có BCTC riêng lẻ | Câu hỏi về riêng lẻ → từ chối |
| D12 | Monorepo: `packages/core` + `apps/{api,cli,web}` | Một `AnswerService` cho mọi giao diện, eval trên CLI đúng cho web | Cấu trúc nặng hơn một script đơn |
| D13 | SSE chỉ stream trạng thái, không stream token | User không bao giờ thấy số chưa qua verifier | Cảm giác chờ lâu hơn, bù bằng thông báo trạng thái |
| D14 | Highlight bằng chứng bằng ảnh render phía server | Đúng trang in và đúng bbox, không phụ thuộc pdf.js xử lý spread | Tốn CPU render, bù bằng cache |
| D15 | **Qdrant** làm vector DB, chạy hai chế độ server/embedded | Hybrid dense + sparse (IDF) + RRF phía server trong 1 lần gọi, lọc payload, cùng client cho production và chấm bài | Thêm một service; kết quả embedded (exact) và server (HNSW) có thể lệch nhẹ |
| D16 | Artefact trung lập (Parquet/JSONL) là nguồn sự thật, DB chỉ là lớp phục vụ | Ship được, nạp được vào mọi chế độ, không khóa vào định dạng DB | Thêm bước `index load` |
| D17 | PostgreSQL (production) / SQLite (chấm bài) qua SQLAlchemy + Alembic | Một schema, migration có version, NUMERIC chính xác | Không dùng được tính năng riêng của Postgres trong bảng dùng chung |

---

## 15. Câu hỏi còn mở

1. ~40 ảnh mid-size: có ảnh nào mang thông tin không? Cần duyệt tay.
2. 6 nửa trang độ phủ < 90% (PDF 152R, 153L, 176R, 182R, 188R, 191L): fallback tọa độ có xử lý hết không?
3. Bộ câu ẩn phân bổ thế nào? Chỉ đoán được (finding #21). Đối phó bằng eval set riêng phủ rộng, không bằng cách tune.
4. PyMuPDF là AGPL: có ảnh hưởng gì nếu bài nộp là repo công khai? (Có thể chấp nhận cho take-home, nhưng cần ghi rõ.)
5. Có ship PDF trong repo không (28 MB)? Nếu không thì endpoint render trang cần `PDF_PATH` hoặc `scripts/fetch_index.sh` tải về.
