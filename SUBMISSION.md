<!-- Fill this in and commit it as SUBMISSION.md at the root of your repository. Keep the headings. -->

# Submission

## How to run
- Clean machine: cần Python 3.11 (`uv` tự tải), [uv](https://docs.astral.sh/uv/), Ollama với `qwen3-embedding:4b` (`ollama pull qwen3-embedding:4b`) và key của LLM đã chọn: `OLLAMA_API_KEY` cho cấu hình mặc định của `.env.example` (`LLM_MODEL=ollama_chat/gemma4:31b`, `OLLAMA_API_BASE=https://ollama.com`), hoặc `OPENAI_API_KEY` cho `LLM_MODEL=openai/...` (Ollama local đã `ollama signin` thì không cần key). `.env.example` chia ba phần: phải điền, tùy chọn, không cần động vào. Hai file đầu vào có sẵn trong repo: `data/techcombank-bao-cao-thuong-nien-2025-vie-update.pdf` và `data/sample_questions.json`. Rồi chạy một lệnh:
  ```bash
  cp .env.example .env    # điền OLLAMA_API_KEY (hoặc export OLLAMA_API_KEY=... trước lệnh dưới)
  bash scripts/smoke_test.sh     # in "OK 10/10"
  ```
  Script đọc cấu hình theo thứ tự biến môi trường, `.env`, `.env.example`; kiểm tra Ollama có model embedding, tạo venv sạch trong thư mục tạm, `uv sync --frozen`, tạo `.env` từ `.env.example` nếu chưa có, build `index/` nếu thiếu, chạy batch 10 câu mẫu và khẳng định đủ 10 dòng, không dòng nào `status="error"`. Thiếu `data/` thì thoát mã 2 kèm hướng dẫn, thiếu key của LLM thì mã 3, thiếu Ollama hoặc model embedding thì mã 4. Chạy tay: `uv sync && uv run ircb chat` (index đã ship; build lại bằng `uv run ircb ingest data/<pdf>`; chi tiết trong `README.md`).
  Đã chạy (2026-10-21, `LLM_MODEL=ollama_chat/gemma4:31b` qua `https://ollama.com`, index ship sẵn): **`OK 10/10`**. Smoke test chỉ khẳng định không dòng nào lỗi; độ đúng của từng câu nằm ở mục Evaluation.
- Different key or local model: mọi thứ đi qua LiteLLM, đổi bằng biến môi trường trong `.env`. `LLM_MODEL=anthropic/...` + `ANTHROPIC_API_KEY`, hoặc `LLM_MODEL=ollama/qwen2.5:14b` + `OLLAMA_API_BASE`. Đổi embedding (`EMBED_MODEL`, `EMBED_DIMENSIONS`) thì chạy `uv run ircb index reembed` (chỉ chạy lại bước embed, có cache; `index/manifest.json` kiểm tra lệch lúc khởi động). Ví dụ `.env` cho OpenAI / Anthropic / Ollama nằm trong `README.md`. Đã chạy thật với OpenAI (`gpt-4o`) và Ollama Cloud (`gpt-oss:120b`, `gemma4:31b`; gọi bằng `OLLAMA_API_KEY` tới `https://ollama.com`, hoặc qua Ollama local đã `ollama signin`). Embedding luôn chạy trên Ollama local (`EMBED_API_BASE`), kể cả khi LLM ở ollama.com. Anthropic **chưa được chạy thử**.
- Batch run: `uv run ircb batch data/sample_questions.json --out eval/reports/run.jsonl [--concurrency N]`. Đầu ra JSONL, mỗi dòng: `id`, `status` (`answered` | `partial` | `refused` | `error`), `answer`, `citations`, `claims`, `calcs`, `latency_ms` (theo từng bước), `cost_usd`, `trace_id`. Câu có trường `turns` chạy như hội thoại nhiều lượt. Một dòng lỗi không làm dừng cả lần chạy.
- Environment variables:

  | Biến | Bắt buộc | Mặc định | Mô tả |
  |---|---|---|---|
  | `LLM_MODEL` | có | `ollama_chat/gemma4:31b` trong `.env.example` | Cú pháp LiteLLM: `openai/…`, `anthropic/…`, `gemini/…`, `ollama_chat/gemma4:31b` (cấu hình đã đo ở Evaluation) |
  | `LLM_MODEL_SMALL` | | = `LLM_MODEL` | Rewriter |
  | `JUDGE_MODEL` | | — | Model cho RAGAS, phải khác `LLM_MODEL` (đã chạy: `ollama_chat/nemotron-3-ultra`) |
  | `VLM_MODEL` | | — | Mô tả ảnh lúc ingest (tùy chọn, chưa dùng) |
  | `OPENAI_API_KEY` | nếu LLM là `openai/...` | — | Embedding không dùng key này (chạy trên Ollama local) |
  | `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | nếu đổi provider | — | |
  | `OLLAMA_API_BASE` | nếu LLM là `ollama_chat/...` | `http://localhost:11434` (`.env.example`: `https://ollama.com`) | Chỉ cho LLM: Ollama local, hoặc `https://ollama.com` kèm `OLLAMA_API_KEY` |
  | `OLLAMA_API_KEY` | có, với cấu hình mặc định của `.env.example` | — | Tạo tại https://ollama.com/settings/keys; không gửi cho embedding |
  | `EMBED_API_BASE` | | `http://localhost:11434` | Ollama phục vụ `EMBED_MODEL` (ollama.com không có model embedding) |
  | `EMBED_MODEL` | | `ollama/qwen3-embedding:4b` | Phải khớp `index/manifest.json`; lệch thì chạy `ircb index reembed` |
  | `EMBED_DIMENSIONS` | | `1024` | Phải khớp manifest |
  | `EMBED_CACHE_DIR` | | `./var/embed_cache` | Cache embedding theo `sha256(text) + model + dimensions` |
  | `LLM_SEED` | | `42` | Dùng khi model không hỗ trợ `temperature=0` |
  | `INDEX_DIR` | | `./index` | |
  | `TOP_K` | | `8` | |
  | `REFUSAL_THRESHOLD` | | `0.35` | Ngưỡng score gate; trên dev không ảnh hưởng kết quả trong khoảng 0,1–0,99 (xem Evaluation) |
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
- Shipped index: `index/` đã được commit (22,4 MB; `index/build/` và `index/.tmp/` gitignore), `index_version` `1acb2897eb97` (chunk mang tên khối; manifest có `periods_in_ranges`, xem `config/units.json`; các số đo ở Evaluation chạy trên `def472d744b6`, cùng chunk nhưng chưa có tên khối), embedding `ollama/qwen3-embedding:4b` 1024 chiều (embed lại toàn bộ trên GPU RTX 4060 mất khoảng 1 phút), 1.145 chunk, 2.974 fact. `index/manifest.json` được kiểm tra lúc khởi động; đổi `EMBED_MODEL` / `EMBED_DIMENSIONS` thì chạy `uv run ircb index reembed`. Build lại từ PDF: `uv run ircb ingest data/techcombank-bao-cao-thuong-nien-2025-vie-update.pdf`.

## Depth track(s) chosen
**Chính: Document Intelligence. Phụ: Retrieval & Reasoning (gọn).**

Khảo sát tài liệu trước khi thiết kế (`scripts/profile_pdf.py`, ~62 giây CPU) cho thấy rủi ro lớn nhất nằm ở bước trích xuất, không ở retrieval: 196/197 trang là spread A3 (mỗi trang PDF chứa hai trang in, nên chunk, bảng và citation phải tách theo nửa trang); 6 bảng vắt qua khe giữa; ba thang đơn vị cùng tồn tại (`nghìn tỷ đồng` ở ô KPI, `tỷ đồng` ở bảng tổng quan, `triệu đồng` ở BCTC, chênh nhau tới 10^6 lần); mũi tên ▲/▼ trên ô KPI là hình vector nên text mất dấu tăng/giảm; ô KPI bị trộn khi đọc theo stream; cùng một nhãn lặp ở dòng cha và dòng con chỉ lệch 4pt thụt lề. Retrieval tốt đến đâu cũng không cứu được một con số đã bị gán sai dòng hay sai đơn vị từ lúc ingest. Độ phủ bảng 98,6% ngay từ baseline cho thấy track này làm xong được trong ngân sách thời gian.

Track phụ chỉ giữ phần rẻ mà hiệu quả: hybrid BM25 + dense với RRF, mở rộng glossary, phép tính khai báo thực thi bằng code. Lý do chi tiết: `docs/DESIGN.md` và các ADR trong `docs/adr/`.

## Architecture
Nguyên tắc: **LLM viết câu, code kiểm tra.** LLM chỉ được gọi ở hai chỗ (viết lại câu hỏi và soạn câu trả lời). Mọi thứ người phân tích sẽ dán vào email (con số, đơn vị, số trang, phép tính, quyết định từ chối với kỳ ngoài báo cáo) đều do code quyết định hoặc kiểm tra. Ý nào không kiểm chứng được bị loại; câu trả lời thành `partial` hoặc bị từ chối, không bao giờ "đoán".

```mermaid
flowchart TB
    subgraph ING["Ingestion: chạy một lần, kết quả ship trong index/"]
        PDF[PDF 197 trang A3] --> SP[Tách spread thành 2 nửa trang<br/>page map: tr. 2p−2 / 2p−1, lệch thì fail]
        SP --> LAY[Layout: word/span, bỏ header/footer lặp]
        LAY --> TB[Bảng: find_tables + kiểm độ phủ số<br/>+ fallback tọa độ; dòng cha/con]
        LAY --> KPI[Ô KPI: parser tọa độ<br/>chiều ▲/▼ từ hình vector]
        LAY --> PR[Văn xuôi, glossary tr. 386–387, ảnh]
        TB & KPI --> FN[Chuẩn hóa: số kiểu VN → Decimal + đơn vị]
        TB & KPI & PR --> CK[Chunk: 1 chunk thuộc 1 trang in<br/>tiền tố chương / khối]
        FN --> ART[(index/: facts.jsonl, chunks.jsonl,<br/>vectors.parquet, glossary, manifest)]
        CK --> EMB[Embed qwen3-embedding:4b + BM25] --> ART
    end
    subgraph QRY["Mỗi câu hỏi"]
        Q[Câu hỏi + lịch sử] --> PG{Period guard<br/>kỳ ngoài báo cáo?}
        PG -- có --> REF[Từ chối + trang gợi ý]
        PG -- không --> RW[Rewriter LLM<br/>câu độc lập + metrics/periods/entity]
        RW --> PF[Prefetch: hybrid chunk + tra fact]
        PF --> GATE{Score gate}
        GATE -- thấp --> REF
        GATE -- đủ --> GEN[Generator LLM<br/>JSON: claims + nguồn + phép tính khai báo]
        GEN --> CALC[Calc executor Decimal]
        CALC --> VER[Verifier deterministic]
        VER --> REN[Renderer: tr. N từ metadata<br/>câu cố định cho partial / mâu thuẫn]
    end
    ART -.nạp lần đầu.-> DB[(Qdrant: vector<br/>SQL: giá trị fact)]
    DB -.-> PF
    DB -.-> VER
```

**Ingestion** (`uv run ircb ingest`, khoảng 3 phút trên máy dev; mỗi bước có cổng chất lượng, build trong thư mục tạm và chỉ thay `index/` khi mọi cổng đều qua):
1. *Spread và page map:* 196/197 trang PDF là spread A3 chứa hai trang in. Mỗi trang PDF p được tách thành nửa trái (tr. 2p−2) và nửa phải (tr. 2p−1); số trang suy ra được đối chiếu với số in trên header từng trang, lệch ở bất kỳ trang nào thì build thất bại. Mọi chunk và fact mang số trang in, không phải số trang PDF.
2. *Layout:* đọc theo word/span, loại furniture (header/footer lặp, số trang) và chỉ số chú thích superscript.
3. *Bảng BCTC:* PyMuPDF `find_tables` theo nửa trang; bảng vắt qua khe giữa được trích trên cả spread và cite `[tr. N, N+1]`. Bước QA đếm số trong text layer so với số trong bảng; nửa trang phủ thấp thì gom từ theo tọa độ. Cấp dòng cha/con suy từ thụt lề x0 và chữ đậm; dòng "Tổng" chỉ được gọi là tổng khi cộng Decimal các dòng trên khớp. Đơn vị lấy từ header cột hoặc dòng "Đơn vị".
4. *Ô KPI:* parser theo tọa độ ghép nhãn, số lớn, đơn vị và mô tả; chiều tăng/giảm đọc từ hình học vector của mũi tên ▲/▼ (text layer không có dấu này), không đọc được thì `unknown`.
5. *Văn xuôi, glossary, ảnh:* văn xuôi theo thứ tự stream (đúng cho bố cục nhiều cột); số infographic được ghép với chú thích của nó; glossary viết tắt tr. 386–387 thành bảng mở rộng truy vấn (CASA ↔ tiền gửi không kỳ hạn); 251 ảnh được phân loại trang trí / có thông tin (`config/images.json`).
6. *Chuẩn hóa fact:* số kiểu Việt Nam (`1.192,34`, `53,4`) thành `decimal.Decimal`, đơn vị bắt buộc trên mọi fact (`nghìn tỷ đồng`, `tỷ đồng`, `triệu đồng`, `%`, ...), kèm nhãn, kỳ, cấp dòng, trang. Thiếu đơn vị thì build thất bại.
7. *Chunk và embed:* mỗi chunk thuộc đúng một trang in (trừ bảng vắt gutter), có tiền tố chương và tên khối / công ty con của trang đó (`config/units.json`, vì tên khối chỉ in ở trang đầu mục). Embed bằng `qwen3-embedding:4b` (1024 chiều) qua Ollama, cache theo hash nội dung; BM25 sparse tự tính với tokenizer tiếng Việt.

Kết quả ship trong `index/`: `chunks.jsonl` (1.145), `facts.jsonl` (2.974), `vectors.parquet`, `glossary.json`, `page_map.json`, `manifest.json` (model, số chiều, phiên bản). Lần chạy đầu, hệ thống nạp artefact vào Qdrant và SQL mà không embed lại; manifest lệch thì nạp lại.

**Lưu trữ và truy hồi:**
- Qdrant có hai collection (`chunks`, `facts`), mỗi điểm có vector dense và vector BM25. **Giá trị số của fact chỉ nằm trong SQL** (SQLite hoặc PostgreSQL, lưu Decimal chính xác); payload Qdrant chỉ có nhãn, kỳ, đơn vị, text. Như vậy con số mà verifier đối chiếu luôn là con số trích từ PDF, không qua vector store.
- Tìm kiếm hybrid: nhánh dense và nhánh BM25 chạy riêng (`exact=True`), cắt top-k theo thứ tự cố định rồi gộp bằng RRF phía client; truy vấn được mở rộng bằng glossary. Mỗi câu lấy 8 chunk và 8 fact.

**Trả lời một câu hỏi** (code lấy dữ liệu trước, LLM gọi một lần, không agent loop):
1. *Period guard* (không LLM): câu hỏi về một năm không có trong báo cáo (ví dụ dự báo 2027) bị từ chối ngay, kèm trang gợi ý. Năm nằm trong một giai đoạn được in (ví dụ "2026–2030") vẫn được hỏi về định hướng, nhưng hỏi con số của năm đó thì từ chối.
2. *Rewriter* (LLM): biến câu hỏi nối tiếp thành câu độc lập dựa trên 3 lượt gần nhất và trạng thái có cấu trúc của lượt trước (`metrics`, `periods`, `entity`). Đây là chỗ xử lý đa lượt: "Còn năm trước thì sao?" sau câu tổng tài sản 2025 thành "Tổng tài sản tại 31/12/2024". Period guard chạy lại trên kết quả.
3. *Prefetch:* một request embedding, tìm hybrid chunk và tra fact cho từng cặp chỉ tiêu × kỳ.
4. *Score gate:* không có hit nào đủ gần (top-1 của nhánh nào cũng dưới `REFUSAL_THRESHOLD` và không được cả hai nhánh cùng tìm thấy) thì từ chối.
5. *Generator* (LLM, một lần gọi, JSON theo schema): mỗi claim là một câu kèm nguồn `fact:<id>` hoặc `chunk:<id>` và đoạn bằng chứng trích nguyên văn. Phép tính (tăng trưởng, tỷ lệ, chênh lệch) được *khai báo* bằng tham chiếu tới fact, câu chỉ chứa chỗ trống `{c1}`; model không tự tính và không bao giờ thấy kết quả. Thiếu số liệu thì được xin thêm đúng một lần (`need_fact`). Không có thông tin thì trả `not_found`.
6. *Calc executor:* tính bằng Decimal, kiểm kỳ (không tính tăng trưởng ngược chiều thời gian), điền kết quả và từ chỉ chiều vào chỗ trống.
7. *Verifier* (deterministic, fail-closed), kiểm từng claim:
   - nguồn có thật trong ngữ cảnh đã lấy; bằng chứng là chuỗi con nguyên văn của chunk;
   - mọi con số trong câu khớp giá trị nguồn sau quy đổi đơn vị và thang (`nghìn tỷ` ↔ `tỷ` ↔ `triệu`), không làm tròn thô hơn nguồn; năm/ngày phải có trong nguồn;
   - từ chỉ chiều ("tăng", "giảm") gắn với đúng chủ ngữ và khớp chiều của nguồn; nguồn không có chiều thì không được viết "tăng";
   - phép tính đã chạy thành công.
   Claim sai bị loại. Còn claim đúng thì câu trả lời là `partial`, kèm một câu cố định chỉ nêu trang, **không lặp lại nội dung claim bị loại**. Hết claim thì từ chối.
8. *Renderer:* số trang lấy từ metadata của nguồn, không do model viết; ghi `[tr. N]` hoặc `[tr. N, M]` sau từng câu.

**Khi hai nguồn mâu thuẫn:** generator phân loại `rounding` (cùng một số, làm tròn khác nhau: viết một lần, cite mọi trang), `definition` (khác định nghĩa chỉ tiêu) hoặc `genuine` (hai số thật sự khác nhau). Ghi chú tự do của model không bao giờ được hiển thị vì chưa kiểm chứng; renderer thêm một câu cố định theo loại, ví dụ "Hai nguồn trong báo cáo cho số liệu khác nhau — cần kiểm tra."

**Phần nào riêng cho tài liệu này:** quy tắc page map của spread, `config/sections.json` (chương, đơn vị mặc định), `config/units.json` (trang của từng khối), `config/images.json` và vị trí glossary. Phần còn lại (trích bảng có QA độ phủ, parser KPI, chuẩn hóa số và đơn vị tiếng Việt, hybrid retrieval, calc khai báo, verifier) không phụ thuộc vào báo cáo này. Nhiều tài liệu hơn cần page map tổng quát và lọc theo `doc_id` (xem "With 10x").

**Giao diện:** kênh chấm bài là CLI: `ircb chat` (REPL đa lượt) và `ircb batch` (chạy danh sách câu hỏi, câu có `turns` chạy như hội thoại). Có thêm `apps/api` (FastAPI, SSE chỉ stream trạng thái; câu trả lời gửi một lần sau verifier, không rò claim bị loại) và `apps/web` (Next.js: chat, chip trích dẫn, trình xem trang in highlight bằng chứng, nút mở toàn bộ PDF, lịch sử chat). Một người dùng, không đăng nhập. Lõi (`packages/core`) không import web/API (import-linter canh).

**Hai chế độ chạy, cùng code:** chấm bài (Qdrant embedded + SQLite, không Docker) và production local (`docker compose`: Qdrant server + PostgreSQL + API + web). Cả hai truy vấn `exact=True` và gộp RRF phía client theo thứ tự cố định, nên trả về cùng top-k (test tích hợp trên tập dev đã chạy với Docker).

## What I tried that did not work
Ghi lại trong lúc làm (xem thêm `docs/worklog.md`). Mỗi mục: đã thử gì, hỏng ra sao, đã đổi gì.

1. **pdfplumber với chiến lược `lines`:** bảng BCTC gần như không có đường kẻ dọc nên pdfplumber trả `None` cho cả cột 31/12/2024 mà không báo lỗi (thử trên PDF 150). Đây là loại lỗi nguy hiểm nhất vì kết quả trông như đúng. Đổi sang PyMuPDF `find_tables` làm mặc định, kèm bộ kiểm tra độ phủ con số.
2. **pdfplumber với chiến lược `text`:** băm vụn chữ ("NỢ PHẢ | I TRẢ"). Bỏ.
3. **`sort=True` khi đọc văn xuôi:** làm xen kẽ hai cột (so sánh trên PDF 8). Dùng thứ tự stream mặc định của InDesign, vốn đúng cho văn bản nhiều cột.
4. **Đọc ô KPI theo stream order:** số, mô tả và đơn vị bị tách và xáo trộn, kiểu "Dư nợ vay · Nghìn tỷ đồng ×4 · 328,1 · 26,9% N/N · Thu nhập lãi thuần · 9,4% N/N" (tr. 59), không biết 9,4% thuộc chỉ tiêu nào. Viết parser riêng theo tọa độ; có golden test.
5. **OCR ảnh để tìm số bị mất khỏi text layer:** thử OCR 272 ảnh lớn, không tìm được ảnh raster nào chứa số liệu vắng mặt trong text layer. Bỏ OCR hàng loạt; text layer đã sạch (Unicode NFC, ToUnicode tốt).
6. **Heuristic gần kề cho từ chỉ chiều trong verifier:** bản đầu kiểm "tăng/giảm" bằng khoảng cách tới một tín hiệu trong nguồn (cửa sổ từ), nhưng nó rò rỉ giữa các chỉ tiêu: một "giảm" của chỉ tiêu này được chứng nhận bởi tín hiệu của chỉ tiêu bên cạnh (ví dụ ROA, "tổng tài sản có rủi ro"). Sau 5 vòng review, thay bằng ràng buộc theo chủ ngữ mệnh đề: mỗi từ chỉ chiều gắn với chủ ngữ của mệnh đề chứa nó; tín hiệu nguồn chỉ tính khi nhãn fact (hoặc chủ ngữ bằng chứng) khớp chủ ngữ đó; phủ định ("không", "chưa") thì chặn; thiếu hẳn tín hiệu cũng chặn. Cái giá: một số câu hợp lệ bị chặn thành `partial` (xem mục 3 của "With 10x").
7. **RAGAS 0.3 trở lên:** kéo `instructor` có giới hạn `rich<15`, làm hạ cấp ngăn xếp CLI. Ghim `ragas==0.2.15` trong nhóm phụ thuộc tùy chọn `eval` (`uv sync --group eval`); đổi lại là API metric cũ hơn, và RAGAS kéo LangChain gián tiếp (chỉ trong nhóm eval, mã của dự án không dùng LangChain).
8. **"13 ô KPI trên tr. 5":** thiết kế ban đầu (và prototype) đếm 13 ô, nhưng test golden chỉ khớp 12: ô thứ 13 là tiêu đề mục "Điểm nhấn 2025" bị luật "span lớn chứa chữ số" nhận nhầm. Parser nay loại tiêu đề mục.
9. **Luật nhãn dòng tổng của kế hoạch ("Tổng ({cha})" cho mọi dòng tổng không nhãn):** gán sai nhãn cho tổng cuối bảng (tr. 329). Thay bằng gán nhãn theo kiểm chứng tổng Decimal: dòng nào thật sự bằng tổng các dòng trên mới được gọi là "Tổng".
10. **Duyệt ảnh:** thiết kế ước tính khoảng 40 ảnh cần xem tay; luật tự động (lặp > 2 lần, > 60% trang, < 1% trang) chỉ loại 64/251 ảnh, còn 187 phải duyệt qua 16 contact sheet. Kết quả: 186 trang trí, đúng 1 ảnh có thông tin (sơ đồ "Customer Brain", tr. 10 PDF, không chứa số). Ghi chú: lượt duyệt là của model và cần người rà lại `config/images.json`.
11. **Bắt năm bằng regex thô trong period guard:** một số lượng như "2027 tỷ" bị coi là năm và gây từ chối nhầm. Thêm điều kiện: không dính dấu phân cách số, không đi liền từ chỉ đại lượng (tỷ, triệu, khách hàng, %, ...). Vẫn còn lọt một số danh từ không nằm trong danh sách (xem "deferred" trong `docs/worklog.md`).

Số đo offline liên quan: độ phủ con số của bảng BCTC là 2.124/2.154 = 98,6% ở baseline (`find_tables` thuần), lên **2.148/2.154 = 99,72%** sau bước fallback tọa độ.

## Evaluation
- Method: 10 câu mẫu chấm từng câu Đúng / Một phần / Sai bằng cách so với `gold_answer`: con số và đơn vị sau quy đổi (1.192 nghìn tỷ = 1.192.344 tỷ đồng, nhưng khác 1.192 tỷ), trang trích dẫn có chứa trang gold không, câu ngoài phạm vi có bị từ chối không. Chấm tay bởi tác giả (đối chiếu từng câu trả lời với `gold_answer` và trang trích dẫn trên PDF). Ngoài 10 câu đó, để có số mà sửa hệ thống, còn ba lớp kiểm tra tự động:
  - *Ingestion:* `ingest_report.json` và golden test trên PDF thật (page map 190/190, ô KPI tr. 5/59/48, CIR ▼ tr. 81, bảng vắt gutter tr. 374–375, bảng BCTC tr. 297/337).
  - *Eval set riêng:* 50 câu tự xây trong `eval/datasets/own_questions.jsonl`, chia 25 dev / 25 test theo 13 category (đa lượt, tính toán lồng, `partial`, 6 câu ngoài phạm vi, ...). Dev dùng để chỉnh prompt và `REFUSAL_THRESHOLD`, test chỉ để báo số. Script tính Recall@8 và MRR theo `gold_printed_pages` (8 chunk cộng 8 fact), citation hit, refusal đúng/sai, khớp số và đơn vị với `gold_values`, và gợi ý Đúng/Một phần/Sai (`suggested_correct`, chưa chấm tay). Gold đối chiếu tay với PDF, không lấy từ output của hệ thống, trừ 5 câu còn chờ người rà lại (own-07, own-09, own-17, own-38, own-49).
  - *Verifier đối nghịch* (chạy trong `uv run pytest`): 64 dòng cố ý sai (sai đơn vị nghìn tỷ ↔ tỷ ↔ triệu, sai dòng cha/con, sai chiều tăng/giảm, số tính toán viết tay thay chỗ trống, đơn vị/tiền tệ lạ, làm tròn thô hơn nguồn như "ROA 2%" khi nguồn ghi 1,5%) **cả 64 đều bị chặn**. Phép tính growth/diff đảo kỳ (a là kỳ trước) bị calc executor loại (`period_order`), nên không còn ra số sai dấu "đã xác minh". Số lọt qua RAGAS judge (faithfulness, ngưỡng 0,5; judge `ollama_chat/nemotron-3-ultra` qua Ollama Cloud, khác `LLM_MODEL`; 2026-10-21, `eval/reports/ragas_20261021T022300Z.json`): **5/64 lọt** (adv-05 chiều không xác định, adv-08 và adv-17 nguồn bịa, adv-09 bằng chứng không nằm trong chunk, adv-24 % không đơn vị lấy từ chunk), verifier chặn cả 64. Ba trong năm lỗi (nguồn bịa, bằng chứng không phải substring) là lỗi cấu trúc mà judge faithfulness không thấy được vì chỉ nhận claim và đoạn bằng chứng; đây là lý do kiểm tra bằng code chứ không bằng LLM judge.
- Results on the 10 published questions (`uv run ircb batch data/sample_questions.json`, `LLM_MODEL=ollama_chat/gemma4:31b`, index `def472d744b6`, 2026-10-21; chấm tay theo Method): **10/10 đúng**, 0 claim bị verifier chặn, citation chứa trang gold ở cả 9 câu có gold page, câu ngoài phạm vi bị từ chối đúng.

  | Câu | Trạng thái | Câu trả lời (rút gọn) | Trang trích dẫn | Trang gold | Đánh giá |
  |---|---|---|---|---|---|
  | sq-01 | answered | 302 chi nhánh và phòng giao dịch; hiện diện tại 29 trên 34 tỉnh thành | 4, 27 | 4 | Đúng |
  | sq-02 | answered | S&P: BB, triển vọng Ổn định; Fitch: BB-, triển vọng Tích cực (lần đầu) | 4, 35, 43 | 4 | Đúng |
  | sq-03 | answered | Tổng tài sản cuối năm 2025: 1.192.344 tỷ đồng | 5, 14 | 5 | Đúng (gold 1.192 nghìn tỷ đồng; không nêu mức tăng 21,8% vì câu hỏi không hỏi) |
  | sq-04 | answered | Tỷ lệ CASA cuối năm 2025: 40,4% | 5, 48 | 5 | Đúng |
  | sq-05 | answered | Tỷ lệ nợ xấu năm 2025: 1,13% | 5, 48 | 5 | Đúng |
  | sq-06 | answered | Tổng thu nhập hoạt động 53.391 tỷ đồng; CAGR 2018–2025: 16,5% | 5, 300 | 5 | Đúng |
  | sq-07 | answered | Dư nợ vay RBG 328,1 nghìn tỷ đồng, tăng 26,9% so với cùng kỳ | 59 | 59 | Đúng |
  | sq-08 | answered | RBG: Khối Ngân hàng Bán lẻ | 387 | 387 | Đúng |
  | sq-09 | answered | CASA: Tiền gửi không kỳ hạn | 386 | 386 | Đúng |
  | sq-10 | refused | Báo cáo không có số liệu/dự báo cho năm 2027 | — | — | Từ chối đúng |

  Lần chạy trước đó cùng ngày, trước khi sửa dòng fact (xem "What the numbers made you change"), được 9/10: sq-04 bị từ chối nhầm; sq-01 có thêm câu mâu thuẫn thừa "Hai số liệu khác nhau do khác định nghĩa chỉ tiêu". Model không tất định tuyệt đối giữa các lần chạy, nên câu thừa ở sq-01 có thể xuất hiện lại.

  *Ngoài 10 câu mẫu (không bắt buộc): eval set riêng* (`uv run ircb eval --split dev|test --run`, `ollama_chat/gemma4:31b`, index `def472d744b6`, 2026-10-21; báo cáo `eval/reports/20261021T021444Z_ac66072.json` và `20261021T022114Z_ac66072.json`, chưa commit vì `eval/reports/` không được theo dõi). "Đúng" ở đây là `suggested_correct` do script gợi ý theo khớp số/đơn vị/trang với gold; **chưa chấm tay**.

  | Split | n | Đúng / Một phần / Sai / Chưa chấm được | citation hit | refusal ok | unit ok | Recall@8 | MRR | Claim bị chặn | Lỗi |
  |---|---|---|---|---|---|---|---|---|---|
  | dev | 25 | 14 / 3 / 8 / 0 | 0,50 | 0,68 | 0,74 | 0,818 | 0,657 | 18,5% (5/27) | 1 |
  | test | 25 | 16 / 1 / 5 / 3 | 0,64 | 0,80 | 0,68 | 0,682 | 0,492 | 16,1% | 1 |

  So với các model trước trên cùng tập dev (cùng thước đo `suggested_correct`): `openai/gpt-4o` 13 / 4 / 7 (claim bị chặn 23,1%), `gpt-oss:120b` 9 / 2 / 13 (44,4%). 3 câu "chưa chấm được" của test là câu thuật ngữ / tường thuật không có `gold_values`, cần chấm tay. Theo category, các lỗi còn lại tập trung ở: bảng vắt gutter (own-22, own-23 bị từ chối), từ chỉ chiều KPI của một khối (own-09, own-10), tường thuật dài (own-42, own-44 bị từ chối), câu ngoài phạm vi về BCTC riêng lẻ (own-47 trả lời bằng số hợp nhất thay vì từ chối), own-07 (không truy hồi được tr. 71, xem "10x"). Hai dòng lỗi (own-33 dev, own-36 test) là JSON thừa ký tự sau đối tượng hoặc sau khối ```` ``` ````; đã sửa ở client và chạy lại hai câu này: own-33 trả lời đúng (tổng tài sản 2025, 2024 và mức tăng 21,8% đã công bố), own-36 `partial`.
- What the numbers made you change (chi tiết từng lần trong `docs/worklog.md`):
  1. *Lần chạy thật đầu (gpt-4o, 2026-10-17):* 10 câu mẫu ra `OK 10/10` theo smoke test nhưng đọc từng câu thì chỉ 5/10 đúng. Nguyên nhân và sửa: fact KPI thiếu kỳ (`period=None`) nên bị lọc khỏi nhánh tra fact theo kỳ; CAGR "2018–2025" bị đọc thành năm 2018; verifier chặn năm/ngày chép từ câu hỏi. Sau sửa 10/10.
  2. *Dev eval lần 1 (gpt-4o):* verifier chặn 32% claim. Thêm ba luật hẹp vẫn gắn chủ ngữ (ô % có dấu tường minh, từ chỉ chiều trích nguyên văn trong khung 5 từ, dòng tiền chi ra trong ngoặc). Kết quả: claim bị chặn 32% → 18,5%, citation_hit 0,36 → 0,45, refusal_ok 0,60 → 0,72, unit_ok 0,58 → 0,74. Một luật khác (gắn chiều chỉ theo con số) đã thử rồi bỏ, vì bộ adversarial bắt được "Tổng tài sản giảm 0,5%" mượn chiều của CIR.
  3. *Dev eval với `gpt-oss:120b`:* verifier loại 44% ý (gpt-4o: 21%), từ chối 13/25 câu (gpt-4o: 7/25). Script so sánh chạy riêng bước retrieval trên cùng câu viết lại cho thấy embedding không phải nguyên nhân (Recall@8 0,773 với cả OpenAI `text-embedding-3-large` và `qwen3-embedding:0.6b`). Vì vậy giữ embedding local miễn phí và tìm LLM khác.
  4. *Kiểm tra chunk offline:* own-07 không bao giờ được truy hồi vì số infographic ("24% N/N") bị tách khỏi nhãn, và 63 chunk có câu trích chữ to bị coi là tiêu đề. Sửa trích xuất (ghép số với chú thích, tiêu đề dài là nội dung, ô KPI không nhãn lấy chú thích bên dưới) đưa Recall@8 0,773 → 0,818 với câu viết lại của gpt-4o.
  5. *Chọn embedding:* `qwen3-embedding:4b` so với 0.6b trên cùng 22 câu dev: với câu viết lại của gpt-oss, Recall@8 0,636 → 0,773, MRR 0,494 → 0,555, không câu nào tụt; độ trễ không đổi (~0,5 giây trên GPU). Đổi sang 4b (ADR 0023).
  6. *Đổi sang gemma4:31b:* câu thử đầu tiên ra `status="error"` vì model bọc JSON trong khối ```` ```json ```` (Ollama Cloud bỏ qua `response_format`); client nay bỏ lớp bọc khi nó bao trọn câu trả lời rồi mới kiểm schema. Sau đó 10 câu mẫu được 9/10: sq-04 (tỷ lệ CASA) bị từ chối vì dòng fact KPI không có tên cột nên không hiện năm ("Tỷ lệ CASA |  | 40,4 %"), model bỏ fact để trích chunk và ghép hai chunk thành một câu trích không nguyên văn. Dòng fact nay ghi kỳ ("năm 2025"), prompt yêu cầu dẫn fact khi có; kết quả 10/10.

  7. *Hiệu chỉnh `REFUSAL_THRESHOLD` trên dev (gemma4):* báo cáo gợi ý 0,64, nhưng quét ngưỡng từ 0,1 đến 0,99 cho cùng một kết quả (refusal recall 0,67 trên 3 câu ngoài phạm vi, false refusal 0,27 trên 22 câu trả lời được): cả 25 câu đều có hit top-1 nằm ở cả hai nhánh dense và BM25, mà gate cho qua hit hai nhánh bất kể ngưỡng. Mọi từ chối đến từ period guard hoặc generator ("not_found"). Con số 0,64 chỉ là điểm giữa của một đoạn phẳng, nên **giữ 0,35**; muốn gate có tác dụng thì phải đổi luật hai nhánh, chưa có số để biện minh.

## Cost and latency
- Ingestion (đo trên máy dev: Intel i5-13500HX, 16 GB RAM, GPU RTX 4060 Laptop 8 GB): build lại từ PDF kể cả embed (`uv run ircb ingest …`) khoảng 3 phút 13 giây, ra 1.145 chunk và 2.974 fact; embed lại toàn bộ bằng `qwen3-embedding:4b` (`ircb index reembed`) dưới 2 phút (lần đầu dừng sau 1 phút 16 giây vì một lỗi HTTP tạm thời của Ollama, lần chạy lại tiếp từ cache rồi xong; tổng thời gian chưa đo riêng). Embedding chạy trên Ollama local nên chi phí API là 0. Đo offline trước đó (embedder giả): bước extract ~78 giây. Khảo sát tài liệu ban đầu mất ~62 giây CPU (container cloud, 1 lõi). Re-embed có cache theo nội dung chunk: chỉ chunk thay đổi mới được embed lại.
- Per query (10 câu mẫu, `ollama_chat/gemma4:31b` trên Ollama Cloud, 2026-10-21): tổng độ trễ p50 5,9 giây, p95 24,0 giây (n = 10, nên p95 gần như là câu chậm nhất, 28,3 giây). Theo bước, p50 trên 9 câu có gọi LLM: rewriter 2,3 giây, prefetch (gồm embed câu hỏi trên GPU) 0,4 giây, generator 2,5 giây, verifier dưới 1 ms. Câu ngoài phạm vi (sq-10) bị period guard từ chối trong vài mili giây, không gọi LLM. Độ trễ của Ollama Cloud dao động: một lần chạy trước, một câu chờ 290 giây ở bước rewriter (gói miễn phí chỉ cho 1 request cùng lúc), lần chạy lại câu đó mất 5 giây. Trên eval cùng ngày (cùng cấu hình): dev p50 6,5 giây, p95 16,2 giây; test p50 9,7 giây, p95 19,1 giây (25 câu mỗi split). Chi phí: 0 USD (`cost_usd` = 0, nằm trong hạn mức miễn phí của Ollama Cloud). Số token mỗi câu chưa đo; nếu trả phí, bảng giá Ollama Cloud cho `gemma4` là 0,14 USD / 1M token vào và 0,40 USD / 1M token ra. Mỗi câu gồm một lần rewriter, một request embedding và một lần generator; hiếm khi thêm một lần do `need_fact`.
- Models used: embedding `ollama/qwen3-embedding:4b` (1024 chiều, cắt từ 2560; cosine; trước đây `openai/text-embedding-3-large` rồi `qwen3-embedding:0.6b`, xem ADR 0022 và 0023). Generation và rewriter: cấu hình đã đo là `ollama_chat/gemma4:31b` trên Ollama Cloud (gọi bằng API key); `.env.example` để cấu hình này làm mặc định, `openai/gpt-4o` là phương án thay thế. Đã chạy thật trước đó với `openai/gpt-4o` và `ollama_chat/gpt-oss:120b-cloud`. RAGAS judge (chỉ cho bộ đối nghịch): `ollama_chat/nemotron-3-ultra`, khác `LLM_MODEL`.

## What I deliberately did not build
Theo thiết kế:
- **Web UI và API là bản gọn:** đề không chấm web nên chỉ làm phần cần để kiểm chứng trích dẫn (chat, thẻ trả lời, trình xem trang). Lõi vẫn không import `fastapi` (import-linter canh).
- **Xác thực, nhiều người dùng, deploy, CI** (mục 4 của đề, "Do NOT build"): không có. Không đăng nhập, không tài khoản: web và API phục vụ một người dùng trên máy local, mọi phiên chat đều hiện trong lịch sử. Không deploy cloud, không orchestration (`docker-compose.yml` chỉ để chạy chế độ production trên máy local), không CI. Bản trước có đăng nhập Clerk, tách lịch sử theo trình duyệt/tài khoản và một workflow CI đẩy image lên ghcr.io; đã gỡ cả ba cho đúng phạm vi đề (migration `0003` bỏ cột `sessions.owner`).
- **OCR hàng loạt:** thử rồi, không tìm ra số mới (xem trên).
- **Reranker:** chỉ thêm nếu eval cho thấy nhiều lỗi do không truy hồi được trang đúng; chưa có số để biện minh.
- **Mô tả ảnh bằng VLM:** chỉ 1 ảnh có thông tin (sơ đồ, không chứa số); `VLM_MODEL` là tùy chọn, chưa dùng.
- **BCTC riêng lẻ:** tài liệu chỉ có BCTC hợp nhất (`TCTD-HN`); câu hỏi về riêng lẻ bị từ chối.
- **Agent loop:** có chủ ý. Đa số câu hỏi cần những thứ đoán trước được (vài chunk, một hai fact theo chỉ tiêu × kỳ), nên code lấy trước rồi gọi LLM một lần: số lần gọi cố định (rewriter + generator, hiếm khi thêm một vòng `need_fact`), độ trễ dự đoán được, kết quả ít dao động giữa các lần chạy, lỗi quy được về từng bước, và chạy được với model local không giỏi tool calling. Đánh đổi: kém linh hoạt với câu hỏi lạ mà rewriter không đoán đúng chỉ tiêu.
- **Stream token:** không cần cho CLI; với web, SSE chỉ nên stream trạng thái để người dùng không thấy số chưa qua verifier.
- Ghi chú giấy phép: PyMuPDF theo AGPL; chấp nhận được cho bài take-home, cần cân nhắc nếu đưa lên sản phẩm.

## With 10x time and budget
Theo thứ tự ưu tiên:
1. Hoàn thiện số liệu với cấu hình hiện tại (`gemma4:31b` + `qwen3-embedding:4b`): chấm tay eval set riêng rồi kiểm định RAGAS với chấm tay (agreement %, Cohen's κ; lệnh có trong `README.md`), xem lại luật hai nhánh của gate để `REFUSAL_THRESHOLD` có tác dụng. Hiện số của eval set chỉ là điểm script gợi ý.
2. Lỗi trích xuất còn lại: bảng fallback của QA độ phủ dựng "bảng" từ trang infographic (101 chunk trên 39 trang, 16 fact phần lớn sai nhãn). (Lỗi tên khối không theo sang trang sau đã sửa: `config/units.json` gắn tên khối vào chunk prose/bảng; retrieval dev Recall@8 0,818 → 0,864, test 0,682 → 0,773; own-07 nay trả lời đúng tr. 71. Chưa chạy lại eval đầy đủ sau sửa.)
3. Giảm chặn nhầm của verifier dựa trên số liệu eval: thêm danh từ đếm được (khách hàng, thẻ, tài khoản) làm đơn vị đếm; đưa ngữ cảnh KPI (chương/mục, ví dụ "TCBS") vào mô tả fact; xử lý nốt các điểm đã ghi trong "deferred" của worklog (qualifier của phân đoạn, nội dung sau từ chỉ chiều).
4. Eval lớn hơn và chấm bởi người thứ hai, thêm alt-pages cho gold nhiều trang hợp lệ; chạy lại cạnh Anthropic để có số cho mục "đổi provider".
5. Chạy test tích hợp hai chế độ trên toàn bộ index thật trong CI (hiện CI chạy trên index tổng hợp và phần so sánh dùng index ship sẵn).
6. Reranker nếu lỗi truy hồi còn cao (benchmark embedding đã làm trên 22 câu dev, xem ADR 0023; cần tập lớn hơn); mô tả ảnh bằng VLM.
7. Đo thời gian kiểm chứng trích dẫn của người dùng trên trình xem trang.
8. Scale lên nhiều tài liệu: page map tổng quát, Table QA thành cổng bắt buộc, Qdrant có replication/quantization, Postgres partition theo `doc_id`, ingestion thành worker xếp hàng.

## Demo video
https://www.youtube.com/watch?v=IvEhkcR8lDU (quay liền một lần, không cắt, trên web chạy bằng Docker: 10 câu mẫu, rồi một câu hỏi nối tiếp "Còn năm trước thì sao?" trong cuộc trò chuyện mới).
