<!-- Fill this in and commit it as SUBMISSION.md at the root of your repository. Keep the headings. -->

# Submission

> **Đọc trước (trung thực về trạng thái).** Toàn bộ mã, test offline và bộ dữ liệu eval đã xong. **Chưa có lần chạy nào với OpenAI API thật** (môi trường làm bài không có key): `index/` chưa được build, chưa có số liệu eval, chưa đo chi phí/độ trễ, chưa quay video. Mọi chỗ cần số đo thật được đánh dấu **`[CHƯA ĐO ...]`** kèm đúng lệnh để chạy. Không có con số nào trong tài liệu này được ước lượng hay bịa; những số có ở đây đều đo được offline và ghi rõ nguồn.

## How to run
- Clean machine: cần Python 3.11 (`uv` tự tải), [uv](https://docs.astral.sh/uv/), và `OPENAI_API_KEY`. Đặt hai file bảo mật vào `data/` (không có trong repo): `data/techcombank-bao-cao-thuong-nien-2025-vie-update.pdf` và `data/sample_questions.json`. Rồi chạy một lệnh:
  ```bash
  export OPENAI_API_KEY=sk-... && bash scripts/smoke_test.sh     # in "OK 10/10"
  ```
  Script tạo venv sạch trong thư mục tạm, `uv sync --frozen`, tạo `.env` từ `.env.example` nếu chưa có, build `index/` nếu thiếu, chạy batch 10 câu mẫu và khẳng định đủ 10 dòng, không dòng nào `status="error"`. Thiếu `data/` thì thoát mã 2 kèm hướng dẫn, thiếu key thì mã 3. Chạy tay: `uv sync && uv run ircb ingest data/<pdf> && uv run ircb chat` (chi tiết trong `README.md`).
  **[CHƯA ĐO — cần chạy `bash scripts/smoke_test.sh` với OPENAI_API_KEY]** (output `OK 10/10` chưa được ghi lại; xem "Smoke test" trong `docs/worklog.md` cho kết quả đã chạy offline: thoát sạch mã 3 với thông báo thiếu key và thiếu index).
- Different key or local model: mọi thứ đi qua LiteLLM, đổi bằng biến môi trường trong `.env`. `LLM_MODEL=anthropic/...` + `ANTHROPIC_API_KEY`, hoặc `LLM_MODEL=ollama/qwen2.5:14b` + `OLLAMA_API_BASE`. Đổi embedding (`EMBED_MODEL`, `EMBED_DIMENSIONS`) thì chạy `uv run ircb index reembed` (chỉ chạy lại bước embed, có cache; `index/manifest.json` kiểm tra lệch lúc khởi động). Ví dụ `.env` cho OpenAI / Anthropic / Ollama nằm trong `README.md`. Chỉ cấu hình OpenAI mặc định là đường đã được thiết kế và test; Anthropic và Ollama **chưa được chạy thử**.
- Batch run: `uv run ircb batch data/sample_questions.json --out eval/reports/run.jsonl [--concurrency N]`. Đầu ra JSONL, mỗi dòng: `id`, `status` (`answered` | `partial` | `refused` | `error`), `answer`, `citations`, `claims`, `calcs`, `latency_ms` (theo từng bước), `cost_usd`, `trace_id`. Câu có trường `turns` chạy như hội thoại nhiều lượt. Một dòng lỗi không làm dừng cả lần chạy.
- Environment variables:

  | Biến | Bắt buộc | Mặc định | Mô tả |
  |---|---|---|---|
  | `LLM_MODEL` | có | `openai/gpt-4o` trong `.env.example` | Cú pháp LiteLLM: `openai/…`, `anthropic/…`, `gemini/…`, `ollama/qwen2.5:14b` |
  | `LLM_MODEL_SMALL` | | = `LLM_MODEL` | Rewriter |
  | `JUDGE_MODEL` | | — | Model cho RAGAS, nên khác `LLM_MODEL` |
  | `VLM_MODEL` | | — | Mô tả ảnh lúc ingest (tùy chọn, chưa dùng) |
  | `OPENAI_API_KEY` | có (mặc định) | — | Dùng cho cả LLM và embedding |
  | `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | nếu đổi provider | — | |
  | `OLLAMA_API_BASE` | nếu chạy local | `http://localhost:11434` | |
  | `EMBED_MODEL` | | `openai/text-embedding-3-large` | Phải khớp `index/manifest.json`; lệch thì chạy `ircb index reembed` |
  | `EMBED_DIMENSIONS` | | `1024` | Phải khớp manifest |
  | `EMBED_CACHE_DIR` | | `./var/embed_cache` | Cache embedding theo `sha256(text) + model + dimensions` |
  | `LLM_SEED` | | `42` | Dùng khi model không hỗ trợ `temperature=0` |
  | `INDEX_DIR` | | `./index` | |
  | `TOP_K` | | `8` | |
  | `REFUSAL_THRESHOLD` | | `0.35` (tạm thời) | Ngưỡng score gate; sẽ được hiệu chỉnh trên tập dev (xem Evaluation) |
  | `TRACE_DIR` | | `./traces` | Trace JSONL từng câu |
  | `LLM_PRICE_IN` / `LLM_PRICE_OUT` | | — | USD / 1M token, để tính `cost_usd` |
  | `APP_ENV` | | `dev` | |
  | `API_HOST` / `API_PORT` / `CORS_ORIGINS` | | `127.0.0.1` / `8000` / `http://localhost:3000` | Dành cho API/web (xem "API và Web" trong `README.md`) |
  | `DATABASE_URL` | | `sqlite:///./var/app.db` | Production: `postgresql+psycopg://ircb:ircb@localhost:5432/ircb` |
  | `QDRANT_URL` | | — | Đặt thì dùng Qdrant server, bỏ trống thì Qdrant embedded |
  | `QDRANT_PATH` | | `./var/qdrant` | Qdrant embedded |
  | `QDRANT_API_KEY` | | — | Nếu server bật API key |
  | `QDRANT_COLLECTION_PREFIX` | | `ircb_` | → `ircb_chunks`, `ircb_facts` |
  | `AUTO_LOAD_INDEX` | | `true` | Tự nạp artefact vào DB nếu thiếu hoặc lệch version |
  | `PAGE_CACHE_DIR` | | `./var/page_cache` | Cache ảnh trang của API/web |
  | `PDF_PATH` | | `./data/techcombank-…-update.pdf` | PDF nguồn |
- Shipped index: đường dẫn dự kiến `index/` (cùng `index/manifest.json`). **Hiện chưa được commit:** việc build cần OpenAI embedding API mà môi trường làm bài không có key. Build bằng `uv run ircb ingest data/techcombank-bao-cao-thuong-nien-2025-vie-update.pdf` (cũng được `scripts/smoke_test.sh` tự gọi khi thiếu `index/`), rồi commit `index/` (trừ `index/build/` và `index/.tmp/` đã gitignore). **[CHƯA ĐO — cần chạy `uv run ircb ingest data/techcombank-bao-cao-thuong-nien-2025-vie-update.pdf` với OPENAI_API_KEY]** để có kích thước thư mục và `index_version` thật. Số đo offline (embedder giả, cùng bước extract): 1.150 chunk, 2.974 fact.

## Depth track(s) chosen
**Chính: Document Intelligence. Phụ: Retrieval & Reasoning (gọn).**

Khảo sát tài liệu (M0, `scripts/profile_pdf.py`, ~62 giây CPU) cho thấy rủi ro lớn nhất nằm ở bước trích xuất, không ở retrieval: 196/197 trang là spread A3 (mỗi trang PDF chứa hai trang in, nên chunk, bảng và citation phải tách theo nửa trang); 6 bảng vắt qua khe giữa; ba thang đơn vị cùng tồn tại (`nghìn tỷ đồng` ở ô KPI, `tỷ đồng` ở bảng tổng quan, `triệu đồng` ở BCTC, chênh nhau tới 10^6 lần); mũi tên ▲/▼ trên ô KPI là hình vector nên text mất dấu tăng/giảm; ô KPI bị trộn khi đọc theo stream; cùng một nhãn lặp ở dòng cha và dòng con chỉ lệch 4pt thụt lề. Retrieval tốt đến đâu cũng không cứu được một con số đã bị gán sai dòng hay sai đơn vị từ lúc ingest. Độ phủ bảng 98,6% ngay từ baseline cho thấy track này làm xong được trong ngân sách thời gian.

Track phụ chỉ giữ phần rẻ mà hiệu quả: hybrid BM25 + dense với RRF, mở rộng glossary, phép tính khai báo thực thi bằng code. Lý do chi tiết: `docs/DESIGN.md` và các ADR trong `docs/adr/`.

## Architecture
Thiết kế (kèm sơ đồ mermaid): `docs/DESIGN.md`. Tóm tắt:

**Ingestion** (chạy một lần, kết quả ship trong `index/`; ba bước extract, normalize, embed, mỗi bước có cổng chất lượng):
1. *Spread splitter + page map:* mỗi trang PDF p thành nửa trái/phải, số trang in = `2p−2` / `2p−1`, kiểm tra với header từng trang; lệch ở bất kỳ trang nào thì fail build.
2. *Layout:* tách theo word/span, bỏ furniture (header lặp, số trang) và footnote superscript.
3. *Bảng:* PyMuPDF `find_tables` theo nửa trang (bảng vắt gutter trích trên cả spread, cite `[tr. N, N+1]`), thêm bước kiểm tra độ phủ số và fallback gom từ theo tọa độ cho nửa trang phủ thấp; suy ra cấp dòng cha/con từ x0 và bold, đơn vị từ header cột hoặc dòng "Đơn vị".
4. *Ô KPI:* parser theo tọa độ (nhãn, số lớn, đơn vị bên phải hoặc bên dưới, mô tả) và đọc chiều tăng/giảm từ hình học vector của mũi tên; không đọc được thì `direction=unknown`.
5. *Chuẩn hóa:* số kiểu Việt Nam (`1.192,34`), đơn vị bắt buộc trên mọi fact, `decimal.Decimal` xuyên suốt. Ra `chunks.jsonl` (mỗi chunk thuộc một trang in), `facts.jsonl`, glossary từ bảng viết tắt tr. 386–387.
6. *Embed:* OpenAI `text-embedding-3-large` 1024 chiều (cache theo hash) cộng BM25 sparse tự tính, nạp vào Qdrant (embedded hoặc server) và SQL (SQLite hoặc PostgreSQL). Giá trị số của fact chỉ nằm trong SQL.

**Query** (code lấy trước dữ liệu, LLM gọi một lần, không agent loop, ADR 0018):
1. *Period guard* xác định (không LLM): kỳ ngoài tài liệu (ví dụ năm 2027) bị từ chối ngay, kèm trang gợi ý.
2. *Rewriter* trả câu hỏi độc lập cùng `metrics[]`, `periods[]`, `entity` (state có cấu trúc giữa các lượt) và glossary expander.
3. *Prefetch song song:* hybrid chunk + `lookup_fact` cho mỗi cặp metric x period, một request embedding; score gate thấp thì từ chối.
4. *Generator* một lần gọi (structured outputs strict): JSON gồm claims có `fact:<id>` / `chunk:<id>` và các phép tính khai báo (`calcs`); tối đa một vòng `need_fact` có kiểm soát.
5. *Calc executor* tính bằng Decimal rồi điền chỗ trống `{cN}`, kèm chiều tăng/giảm do code render; model không bao giờ thấy kết quả (ADR 0019).
6. *Verifier* deterministic kiểm từng claim: số có trong nguồn, đúng đơn vị và thang, trang cite chứa claim, từ chỉ chiều khớp nguồn. Claim sai bị loại và câu trả lời là `partial` với một câu cố định chỉ nêu trang, không lặp lại nội dung claim bị loại; hết claim thì từ chối (ADR 0020). Số trang chỉ lấy từ metadata, model không tự viết số trang.

**API và web** (ngoài phạm vi chấm, có sẵn để xem): `apps/api` (FastAPI, SSE chỉ stream trạng thái, câu trả lời gửi một lần sau verifier, không rò claim bị loại) và `apps/web` (Next.js: chat, thẻ trả lời có chip trích dẫn/phép tính, trình xem trang in tô sáng bằng chứng, cần PDF trong `data/`). Cách chạy: mục "API và Web" trong `README.md`. Chưa đo gì thêm cho phần này ngoài test offline và một lần chạy thử tay (xem `docs/worklog.md`).

Hai chế độ chạy cùng code: chấm bài (Qdrant embedded + SQLite, không Docker) và production local (`docker-compose.yml`: Qdrant server + PostgreSQL), cả hai đều query `exact=True`.

## What I tried that did not work
Ghi lại trong lúc làm (xem thêm `docs/worklog.md`). Mỗi mục: đã thử gì, hỏng ra sao, đã đổi gì.

1. **pdfplumber với chiến lược `lines`:** bảng BCTC gần như không có đường kẻ dọc nên pdfplumber trả `None` cho cả cột 31/12/2024 mà không báo lỗi (thử trên PDF 150). Đây là loại lỗi nguy hiểm nhất vì kết quả trông như đúng. Đổi sang PyMuPDF `find_tables` làm mặc định, kèm bộ kiểm tra độ phủ con số (D4).
2. **pdfplumber với chiến lược `text`:** băm vụn chữ ("NỢ PHẢ | I TRẢ"). Bỏ.
3. **`sort=True` khi đọc văn xuôi:** làm xen kẽ hai cột (so sánh trên PDF 8). Dùng thứ tự stream mặc định của InDesign, vốn đúng cho văn bản nhiều cột.
4. **Đọc ô KPI theo stream order:** số, mô tả và đơn vị bị tách và xáo trộn, kiểu "Dư nợ vay · Nghìn tỷ đồng ×4 · 328,1 · 26,9% N/N · Thu nhập lãi thuần · 9,4% N/N" (tr. 59), không biết 9,4% thuộc chỉ tiêu nào. Viết parser riêng theo tọa độ; có golden test.
5. **OCR ảnh để tìm số bị mất khỏi text layer:** thử OCR 272 ảnh lớn, không tìm được ảnh raster nào chứa số liệu vắng mặt trong text layer. Bỏ OCR hàng loạt (D8); text layer đã sạch (Unicode NFC, ToUnicode tốt).
6. **Heuristic gần kề cho từ chỉ chiều trong verifier:** bản đầu kiểm "tăng/giảm" bằng khoảng cách tới một tín hiệu trong nguồn (cửa sổ từ), nhưng nó rò rỉ giữa các chỉ tiêu: một "giảm" của chỉ tiêu này được chứng nhận bởi tín hiệu của chỉ tiêu bên cạnh (ví dụ ROA, "tổng tài sản có rủi ro"). Sau 5 vòng review, thay bằng ràng buộc theo chủ ngữ mệnh đề: mỗi từ chỉ chiều gắn với chủ ngữ của mệnh đề chứa nó; tín hiệu nguồn chỉ tính khi nhãn fact (hoặc chủ ngữ bằng chứng) khớp chủ ngữ đó; phủ định ("không", "chưa") thì chặn; thiếu hẳn tín hiệu cũng chặn. Cái giá: một số câu hợp lệ bị chặn thành `partial` (xem giới hạn đã biết ở Evaluation).
7. **RAGAS 0.3 trở lên:** kéo `instructor` có giới hạn `rich<15`, làm hạ cấp ngăn xếp CLI. Ghim `ragas==0.2.15` trong nhóm phụ thuộc tùy chọn `eval` (`uv sync --group eval`); đổi lại là API metric cũ hơn, và RAGAS kéo LangChain gián tiếp (chỉ trong nhóm eval, mã của dự án không dùng LangChain).
8. **"13 ô KPI trên tr. 5":** thiết kế ban đầu (và prototype) đếm 13 ô, nhưng test golden chỉ khớp 12: ô thứ 13 là tiêu đề mục "Điểm nhấn 2025" bị luật "span lớn chứa chữ số" nhận nhầm. Parser nay loại tiêu đề mục.
9. **Luật nhãn dòng tổng của kế hoạch ("Tổng ({cha})" cho mọi dòng tổng không nhãn):** gán sai nhãn cho tổng cuối bảng (tr. 329). Thay bằng gán nhãn theo kiểm chứng tổng Decimal: dòng nào thật sự bằng tổng các dòng trên mới được gọi là "Tổng".
10. **Duyệt ảnh:** thiết kế ước tính khoảng 40 ảnh cần xem tay; luật tự động (lặp > 2 lần, > 60% trang, < 1% trang) chỉ loại 64/251 ảnh, còn 187 phải duyệt qua 16 contact sheet. Kết quả: 186 trang trí, đúng 1 ảnh có thông tin (sơ đồ "Customer Brain", tr. 10 PDF, không chứa số). Ghi chú: lượt duyệt là của model và cần người rà lại `config/images.json`.
11. **Bắt năm bằng regex thô trong period guard:** một số lượng như "2027 tỷ" bị coi là năm và gây từ chối nhầm. Thêm điều kiện: không dính dấu phân cách số, không đi liền từ chỉ đại lượng (tỷ, triệu, khách hàng, %, ...). Vẫn còn lọt một số danh từ không nằm trong danh sách (xem "deferred" trong `docs/worklog.md`).

Số đo offline liên quan: độ phủ con số của bảng BCTC là 2.124/2.154 = 98,6% ở baseline (`find_tables` thuần), lên **2.148/2.154 = 99,72%** sau bước fallback tọa độ (Task 7).

## Evaluation
- Method: bốn lớp. (1) Ingestion: `ingest_report.json` và golden test (page map 190/190, ô KPI tr. 5/59/48, CIR ▼ tr. 81, bảng vắt gutter tr. 374–375, bảng BCTC tr. 297/337). (2) Retrieval: Recall@8 và MRR theo `gold_printed_pages` (Recall@8 đếm 8 chunk cộng 8 fact). (3) Citation và số liệu tự động: citation hit, refusal đúng/sai, khớp số và đơn vị với `gold_values` sau quy đổi (1.192 nghìn tỷ = 1.192.344.137 triệu, nhưng khác 1.192 tỷ). (4) Đúng/Một phần/Sai: **chấm tay** (script chỉ gợi ý `suggested_correct`). RAGAS (faithfulness, context precision/recall, factual correctness) chỉ là tín hiệu phụ, bắt buộc kiểm định bằng agreement % và Cohen's κ so với chấm tay trước khi báo cáo, `JUDGE_MODEL` khác `LLM_MODEL`. Báo theo từng tiêu chí và từng category, không gộp một con số. Gold của eval set riêng được đối chiếu tay với PDF, không lấy từ output của hệ thống, trừ 5 câu còn chờ người rà lại (own-07, own-09, own-17, own-38, own-49; xem dòng Dataset).
- Dataset (đo offline): 50 câu tự xây trong `eval/datasets/own_questions.jsonl`, chia 25 dev / 25 test theo từng category (13 category, gồm đa lượt, tính toán lồng, `partial`, 6 câu ngoài phạm vi); 10 câu mẫu báo cáo riêng. Dev dùng để hiệu chỉnh `REFUSAL_THRESHOLD` và chỉnh prompt; test chỉ chạy để báo số cuối. Gold có 5 câu cần người rà lại với PDF: own-07, own-09, own-17, own-38, own-49.
- Test đối nghịch của verifier (đo offline, chạy trong `uv run pytest`): 64 dòng cố ý sai (sai đơn vị nghìn tỷ ↔ tỷ ↔ triệu, sai dòng cha/con, sai chiều tăng/giảm, số tính toán viết tay thay chỗ trống, đơn vị/tiền tệ lạ, làm tròn thô hơn nguồn như "ROA 2%" khi nguồn ghi 1,5%) **cả 64 đều bị chặn**. Phép tính growth/diff đảo kỳ (a là kỳ trước) bị calc executor loại (`period_order`), nên không còn ra số sai dấu "đã xác minh". Số lọt qua RAGAS judge: **[CHƯA ĐO — cần chạy `uv sync --group eval && uv run python eval/runners/ragas_eval.py --judge $JUDGE_MODEL --adversarial eval/datasets/adversarial.jsonl` với OPENAI_API_KEY]**.
- Results on the 10 published questions: **[CHƯA ĐO — cần chạy `uv run ircb batch data/sample_questions.json --out eval/reports/sample_run.jsonl` với OPENAI_API_KEY, rồi chấm tay từng câu (đúng / một phần / sai, citation hit, refusal)]**. Bảng kết quả mong đợi: một dòng mỗi câu sq-01…sq-10 theo các tiêu chí trên.
- Results on own eval set (dev, test riêng): **[CHƯA ĐO — cần chạy `uv run ircb eval --split dev --run` rồi `uv run ircb eval --split test --run` với OPENAI_API_KEY]**, gồm Recall@8, MRR, citation hit, refusal ok, unit ok theo category, và phiếu chấm tay `eval/scoring/score_sheet.csv`.
- Độ đồng thuận RAGAS với chấm tay (agreement %, Cohen's κ): **[CHƯA ĐO — cần chạy `uv run python eval/runners/ragas_eval.py --judge $JUDGE_MODEL --split dev` rồi `uv run python eval/runners/judge_agreement.py eval/scoring/score_sheet.csv eval/reports/ragas_<ts>.json` sau khi chấm tay ~40 câu]**.
- What the numbers made you change: **[CHƯA ĐO — chưa có số liệu để rút ra thay đổi; điền sau lần chạy eval đầu tiên]**. Ngưỡng `REFUSAL_THRESHOLD=0.35` hiện chỉ là giá trị tạm; báo cáo của `ircb eval --split dev` ghi ngưỡng gợi ý cân bằng refusal recall ≥ 0,9 và false refusal ≤ 0,15 trên tập dev, cần chạy thật rồi đặt lại, và chạy thêm một lần xác nhận.
- Giới hạn đã biết sẽ ảnh hưởng điểm (dự đoán từ thiết kế, **chưa kiểm chứng bằng số**): verifier fail-closed nên số lượng kèm đại lượng ("15,5 triệu khách hàng") luôn bị chặn; câu hỏi chiều tăng/giảm KPI của một khối (ví dụ "CIR của TCBS giảm 0,5%") có thể bị chặn vì từ vựng fact chưa chứa "TCBS". Cả hai là chặn nhầm an toàn (kết quả `partial`) và nằm trong danh sách theo dõi của eval.

## Cost and latency
- Ingestion: **[CHƯA ĐO — cần chạy `uv run ircb ingest data/techcombank-bao-cao-thuong-nien-2025-vie-update.pdf` với OPENAI_API_KEY (ghi chi phí embedding từ dashboard OpenAI và wall-clock bước embed)]**. Đo offline (embedder giả): bước extract ~78 giây, ra 1.150 chunk và 2.974 fact; số này chưa gồm thời gian gọi API embedding. Khảo sát M0 mất ~62 giây CPU (container cloud, 1 lõi). Re-embed khi đổi model có cache nên rẻ hơn lần build đầu.
- Per query: **[CHƯA ĐO — cần chạy `uv run ircb batch data/sample_questions.json --out eval/reports/sample_run.jsonl` với OPENAI_API_KEY và `LLM_PRICE_IN` / `LLM_PRICE_OUT` đã đặt; đọc `cost_usd` và `latency_ms` từng dòng để tính chi phí/câu và p50, p95]**. Theo thiết kế, mỗi câu gồm một lần rewriter (model nhỏ), một request embedding và một lần generator; hiếm khi thêm một lần do `need_fact`.
- Models used: embedding `openai/text-embedding-3-large` (1024 chiều, cosine). Generation và rewriter: mặc định `LLM_MODEL=openai/gpt-4o` trong `.env.example`; **chọn model cụ thể là quyết định tạm thời**, chốt sau khi đo latency và chi phí trên tập dev (spec §15.6). RAGAS judge: `JUDGE_MODEL` (một model OpenAI khác, chưa đặt).

## What I deliberately did not build
Theo thiết kế:
- **Web UI và API là bản gọn:** đề không chấm web nên chỉ làm phần cần để kiểm chứng trích dẫn (chat, thẻ trả lời, trình xem trang). Lõi vẫn không import `fastapi` (import-linter canh).
- **Docker image cho api/web:** chưa có; `docker-compose.yml` chỉ chứa Qdrant và PostgreSQL, API và web chạy trên máy host.
- **Trang lịch sử phiên (sessions):** API có `GET /v1/sessions/{id}` nhưng web chưa có trang liệt kê/xem lại các phiên.
- **Auth, nhiều người dùng, deploy cloud, CI:** ngoài phạm vi take-home.
- **OCR hàng loạt:** thử rồi, không tìm ra số mới (xem trên).
- **Reranker:** chỉ thêm nếu eval cho thấy `R-miss` cao; chưa có số để biện minh.
- **Mô tả ảnh bằng VLM:** chỉ 1 ảnh có thông tin (sơ đồ, không chứa số); `VLM_MODEL` là tùy chọn, chưa dùng.
- **BCTC riêng lẻ:** tài liệu chỉ có BCTC hợp nhất (`TCTD-HN`); câu hỏi về riêng lẻ bị từ chối (D11).
- **Agent loop:** có chủ ý, xem ADR 0018.
- **Stream token:** không cần cho CLI; với web, SSE chỉ nên stream trạng thái để người dùng không thấy số chưa qua verifier.
- Ghi chú giấy phép: PyMuPDF theo AGPL (D4); chấp nhận được cho bài take-home, cần cân nhắc nếu đưa lên sản phẩm.

## With 10x time and budget
Theo thứ tự ưu tiên:
1. Chạy toàn bộ quy trình với API thật và hoàn thiện số liệu: build `index/` và commit, eval dev/test, chấm tay đủ ~40 câu, kiểm định RAGAS (agreement, κ), hiệu chỉnh `REFUSAL_THRESHOLD`, đo chi phí và p50/p95. Đây là phần còn thiếu lớn nhất của bài nộp hiện tại.
2. Giảm chặn nhầm của verifier dựa trên số liệu eval: thêm danh từ đếm được (khách hàng, thẻ, tài khoản) làm đơn vị đếm; đưa ngữ cảnh KPI (chương/mục, ví dụ "TCBS") vào mô tả fact; xử lý nốt các điểm đã ghi trong "deferred" của worklog (qualifier của phân đoạn, nội dung sau từ chỉ chiều).
3. Eval lớn hơn và chấm bởi người thứ hai, thêm alt-pages cho gold nhiều trang hợp lệ; chạy lại cạnh model khác (Anthropic, Ollama) để có số cho mục "đổi provider".
4. Chạy tích hợp trên Qdrant server + PostgreSQL thật với index thật (hiện chỉ có test trên index tổng hợp, chưa chạy với Docker daemon).
5. Benchmark embedding và (nếu `R-miss` cao) reranker; mô tả ảnh bằng VLM.
6. Docker image cho api/web, trang lịch sử phiên, và đo thời gian kiểm chứng trích dẫn của người dùng trên trình xem trang.
7. Scale lên nhiều tài liệu: page map tổng quát, Table QA thành cổng bắt buộc, Qdrant có replication/quantization, Postgres partition theo `doc_id`, ingestion thành worker xếp hàng (spec §11).

## Demo video
**[CHƯA CÓ — cần quay 3–5 phút một take trên CLI (`uv run ircb chat`): 10 câu mẫu, có câu bị từ chối, một câu `partial`, một câu tính toán, một follow-up; dán link vào đây]**
