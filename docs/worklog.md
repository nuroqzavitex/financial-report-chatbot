# Worklog

## Task 9 - image triage (spec 5.14)

- Rules (repeated > 2x, > 60% page, < 1% page) marked 64 of 251 images `decorative`; 187 remained `review` (spec estimated ~40; the PDF has many full-page-width photos and portraits).
- Manual pass over 16 contact sheets (var/contact/, gitignored) by Claude (`reviewed_by: claude-first-pass`); the user will spot-check config/images.json.
- Result: 186 decorative (photos, portraits, backgrounds, chapter numerals), 1 informative (xref 238, PDF p.10 "Customer Brain" strategy diagram; no numeric data).
- Time: system clock 23:10:38 (sheets generated) to 23:11:22 (labels written); the visual review itself ran inside that window of tool calls.
- No VLM description was generated (no API key). The informative image is listed for Task 12 (chunk content_type="figure").

## 2026-10-16 → 2026-10-17 - Tasks 11-24: từ embedding đến đóng gói

Tất cả được làm và test **offline** (embedder và LLM giả). Môi trường làm bài không có `OPENAI_API_KEY` và không có Docker daemon, nên mọi bước cần API hoặc dịch vụ thật được hoãn và liệt kê ở cuối mục này kèm lệnh chạy.

### Đã xây

| Task | Nội dung |
|---|---|
| 11 | Tokenizer tiếng Việt (NFC, mã có `/` hoặc `-` giữ nguyên), BM25 sparse, `Embedder` có cache theo `sha256(text)+model+dimensions`, retry khi timeout |
| 12 | Pipeline ingestion ba bước (extract, normalize, embed) với cổng chất lượng, build staged và atomic vào `index/`; đo offline với embedder giả: 1.150 chunk, 2.974 fact; bước extract ~78 giây |
| 13 | Mô hình SQLAlchemy, migration Alembic đầu tiên, repo cho fact và session (cột `NUMERIC`, SQLite và PostgreSQL) |
| 14 | `QdrantStore` hybrid dense + sparse (RRF, `exact=True`), loader idempotent, nạp lại khi đổi version |
| 15 | Prefetch song song: hybrid chunk + `lookup_fact` cho mỗi cặp metric x period, mở rộng glossary, score gate (xét top-1 mỗi nhánh) |
| 16 | `LLMClient` qua LiteLLM: JSON strict, retry, chi phí tính bằng Decimal, trace JSONL; response hỏng thành `LLMError` |
| 17 | Period guard xác định và rewriter có cấu trúc (`metrics[]`, `periods[]`, `entity`) |
| 18 | Calc executor khai báo (`growth`, `diff`, `ratio`, `convert`), ràng buộc đơn vị/chỉ tiêu/kỳ, lồng một tầng, cơ sở không dương bị từ chối (`non_positive_base`) |
| 19 | Verifier theo từng claim, fail-closed (đơn vị, tiền tệ, từ chỉ chiều); 5 vòng review; bộ đối nghịch 60 dòng, cả 60 bị chặn |
| 20 | Generator một lần gọi, `need_fact` tối đa một vòng, renderer `[tr. N]`; prompt có `PROMPT_VERSION`, `.gitattributes` ghim LF cho prompts |
| 21 | `AnswerService` và CLI typer: `ingest`, `index load|reembed`, `chat`, `batch`, `profile` |
| 22 | Eval: dataset 50 câu (25 dev / 25 test), runner chấm tự động, hiệu chỉnh ngưỡng, phiếu chấm tay, RAGAS (ghim 0.2.15, nhóm `eval`), độ đồng thuận (agreement, κ) và subcommand `ircb eval` |
| 23 | `docker-compose.yml` (Qdrant + PostgreSQL), test tương đương hai chế độ trên index tổng hợp |
| 24 | README, SUBMISSION, ADR 0018-0021, `scripts/smoke_test.sh`, sửa spec (12 ô KPI), sửa target `make ingest` |

### Số đo offline (không cần API)

- M0 profiling: ~62 giây CPU.
- Độ phủ con số bảng BCTC: baseline `find_tables` 2.124/2.154 = 98,6%; sau fallback tọa độ (Task 7) 2.148/2.154 = 99,72%.
- Ingestion extract ~78 giây; 1.150 chunk, 2.974 fact (build bằng embedder giả).
- Bộ đối nghịch của verifier: 60 dòng, cả 60 bị chặn.
- Eval set riêng: 50 câu, 25 dev / 25 test.
- Test suite mặc định (`uv run pytest`): 540 passed, 3 deselected (marker `integration`) trong 252 giây; `ruff check`, `ruff format packages apps eval`, `mypy` (50 file) và `lint-imports` (1 contract kept) đều sạch

### Smoke test (`scripts/smoke_test.sh`) chạy trong môi trường không có key

```
$ bash scripts/smoke_test.sh
MISSING: OPENAI_API_KEY is not set in the environment.
index/ is not built yet (no index/manifest.json): the first run builds it with the embedding API,
so a key is required: export OPENAI_API_KEY=sk-... and run this script again.
exit=3
```

Thoát sạch với thông báo thiếu key và thiếu index. Đường `OK 10/10` chưa chạy được ở đây.

### Điều đã thử và không hiệu quả (bổ sung cho SUBMISSION.md)

- Luật nhãn "Tổng ({cha})" của kế hoạch gán sai tổng cuối bảng (tr. 329): đổi sang gán nhãn bằng kiểm chứng tổng Decimal.
- Heuristic khoảng cách cho từ chỉ chiều trong verifier rò rỉ giữa các chỉ tiêu qua nhiều vòng sửa; thay bằng ràng buộc theo chủ ngữ mệnh đề ở vòng 4-5.
- RAGAS 0.3+ kéo `instructor` (`rich<15`) làm hạ cấp ngăn xếp CLI: ghim 0.2.15.
- "13 ô KPI trên tr. 5" thực ra là 12 ô và một tiêu đề "Điểm nhấn 2025" bị nhận nhầm.
- Luật năm trong period guard từ chối nhầm các đại lượng ("2027 tỷ"): thêm điều kiện kề dấu phân cách và từ chỉ đại lượng.

### DEFERRED: cần `OPENAI_API_KEY` hoặc Docker (chạy theo thứ tự)

Đặt `export OPENAI_API_KEY=sk-...`, đặt `data/` đúng tên (xem README), rồi:

1. **Build `index/` thật (Task 12) và commit:**
   `uv run ircb ingest data/techcombank-bao-cao-thuong-nien-2025-vie-update.pdf`, sau đó `git add index/` (không `data/`). Ghi `index_version`, kích thước, chi phí embedding, wall-clock vào SUBMISSION.md.
2. **Batch thật trên 10 câu mẫu (Task 21):**
   `uv run ircb batch data/sample_questions.json --out eval/reports/sample_run.jsonl`
   rồi chấm tay từng câu (đúng/một phần/sai), tính p50, p95 từ `latency_ms`, và chi phí/câu từ `cost_usd` (đặt `LLM_PRICE_IN`, `LLM_PRICE_OUT`).
3. **Eval v1 và hiệu chỉnh ngưỡng (Task 22):**
   `uv run ircb eval --split dev --run`, đọc ngưỡng gợi ý trong `eval/reports/*.json`, đặt `REFUSAL_THRESHOLD`, chạy lại một lần xác nhận; sau đó `uv run ircb eval --split test --run` để lấy số cuối.
4. **Chấm tay và RAGAS (Task 22):** điền `manual_label` trong `eval/scoring/score_sheet.csv` (~40 câu), rồi
   `uv sync --group eval`
   `uv run python eval/runners/ragas_eval.py --judge $JUDGE_MODEL --split dev`
   `uv run python eval/runners/judge_agreement.py eval/scoring/score_sheet.csv eval/reports/ragas_<ts>.json`
5. **Đối nghịch qua RAGAS (Task 22):**
   `uv run python eval/runners/ragas_eval.py --judge $JUDGE_MODEL --adversarial eval/datasets/adversarial.jsonl`
6. **Người rà gold:** đối chiếu tay với PDF các câu own-07, own-09, own-17, own-38, own-49 trong `eval/datasets/own_questions.jsonl`.
7. **Test tích hợp với dịch vụ thật (Task 23; cần Docker daemon):**
   `docker compose up -d --wait`
   `QDRANT_URL=http://localhost:6333 DATABASE_URL=postgresql+psycopg://ircb:ircb@localhost:5432/ircb uv run pytest -m integration`
   Tag ảnh `qdrant/qdrant:v1.19.0` chưa được kiểm tra trên registry; nâng lên v1.19.x mới nhất nếu cần. Với index thật, test so sánh top-k hai chế độ chạy cả trên tập dev.
8. **Smoke test trên máy sạch (Task 24 bước 3):** `bash scripts/smoke_test.sh` phải in `OK 10/10`; dán output vào SUBMISSION.md.
9. **Video demo (Task 24 bước 6, M7):** 3-5 phút một take trên `uv run ircb chat`: 10 câu mẫu, có câu bị từ chối, một câu `partial`, một câu tính toán, một follow-up; dán link vào SUBMISSION.md.
10. **Duyệt ảnh (Task 9):** người rà `config/images.json` (186 trang trí, 1 informative: xref 238, PDF tr. 10); mô tả VLM cho ảnh đó chưa tạo (cần `VLM_MODEL` và key).
11. **Theo dõi khi có số liệu eval:** (a) số lượng kèm đại lượng ("15,5 triệu khách hàng") luôn bị verifier chặn: nếu false refusal đáng kể thì thêm danh từ đếm (khách hàng, thẻ, tài khoản, người dùng, giao dịch) làm đơn vị đếm; (b) fact của tr. 81 thiếu từ "TCBS" nên "CIR của TCBS giảm 0,5%" bị chặn: đưa ngữ cảnh KPI (chương/mục) vào mô tả fact lúc ingest; (c) Recall@8 hiện đếm 8 chunk + 8 fact.

### Điểm nhỏ còn mở (đã ghi trong review từng task, chưa sửa)

- CLI: `reembed` chưa staged/atomic; hai dạng dòng lỗi trong batch; `--concurrency > 1` chưa test an toàn luồng với Qdrant embedded và cache embedding.
- Verifier (chặn nhầm an toàn hoặc lọt hiếm, ghi ở review Task 19): qualifier của phân đoạn có thể bị bỏ ("Dư nợ vay của ngân hàng tăng 26,9%" qua với fact RBG), nội dung sau từ chỉ chiều không kiểm ("... so với VPBank"), năm sai được chứng nhận bởi text chunk ("2021-2025"), tiền tệ viết sau dấu ngắt mệnh đề vẫn lọt, chủ ngữ so sánh theo tập từ nên mất thứ tự từ.
- Period guard: "2027 tỷ lệ" / "năm 2027 đồng thời" lọt do thiếu `\b`; danh từ đếm ngoài danh sách bị coi là năm.
- Ingestion: tên chương bị lặp ở hai nửa trang ("Nền Nền tảng tảng"); `assert_unique_ids` raise trước khi ghi report; bảng không có đơn vị (unit=None) chỉ sinh chunk, không sinh fact (~92 bảng phi BCTC).
- Storage: `upsert` kiểu select-then-insert không an toàn đồng thời; Qdrant `reset` toàn cục trong khi SQL xóa theo `doc_id` (chấp nhận với một tài liệu); admin PostgreSQL của test tích hợp cần quyền CREATEDB.
- Eval: Recall@8 chưa có `alt_pages` (own-01, own-28); own-09 "0,5 điểm %" có thể fail `unit_ok`; `load_jsonl` bỏ im lặng dòng hỏng; dòng unanswerable hiện `citation_hit` True; `_contexts`/`_index_texts` của ragas_eval chưa có test.

## 2026-10-17 - Sửa sau review cuối nhánh

Review toàn nhánh (`.superpowers/sdd/2026-10-16-ircb-core-cli-eval/final-review.md`) tìm ra 2 lỗi nghiêm trọng và 8 lỗi quan trọng; tất cả đã sửa, mỗi lỗi có test hồi quy (offline):

- **C1:** payload chunk trong Qdrant thiếu `pdf_page`, `half`, `fact_ids`, `bbox` nên mọi câu hỏi thật crash ở prefetch. Loader nay ghi đủ `Chunk`; index nạp bằng loader cũ được tự nạp lại.
- **C2:** dòng "Chưa xác minh được" lặp lại nội dung (và con số sai) của claim bị loại. Nay là câu cố định chỉ nêu trang; dòng batch bỏ `text` của claim bị loại, dòng `refused` không mang claim/calc.
- **I1:** growth/diff đảo kỳ cho số sai dấu nhưng qua verifier. Nay `a` phải là kỳ sau (`period_order`); trộn fact với kết quả calc phái sinh bị loại (`operand_mix`).
- **I2:** dung sai theo độ chính xác model tự viết ("ROA 2%" qua khi nguồn 1,5%). Nay cùng đơn vị thì không được làm tròn thô hơn nguồn; khác thang thì cần ≥ 3 chữ số có nghĩa (quy đổi chính xác vẫn qua).
- **I3 / I4:** `status: "partial"` của generator được giữ; ghi chú mâu thuẫn tự do của model không bao giờ hiển thị (câu cố định theo loại).
- **I5 / I6 / I7:** tự tạo `var/` và các thư mục runtime; Qdrant rỗng hoặc lệch số điểm so với manifest thì tự nạp lại; lỗi khởi động của CLI là một dòng kèm lệnh cần chạy, không traceback.
- **I8:** thêm test end-to-end trong bộ test mặc định (artefact thật, Qdrant embedded + SQLite, LLM giả); test golden kiểm chéo `chunk.fact_ids` với facts.

## 2026-10-17 - Lần chạy thật đầu tiên (OpenAI API)

Index `46c78c954ba6`: 1150 chunk, 2974 fact; page map khớp, không fact nào thiếu đơn vị; 180/315 bảng không có đơn vị (chỉ sinh chunk). Smoke test `OK 10/10` nhưng đọc từng câu thì lần đầu chỉ 5/10 đúng. Nguyên nhân gốc (mỗi lỗi có test hồi quy):

- **Fact KPI `period=None`** nên bị lọc khỏi nhánh tìm fact theo kỳ; cùng với chunk KPI gộp 12 chỉ tiêu (embedding loãng, tr. 5 không vào top 60 dense) làm số liệu tr. 5 không truy hồi được. KPI nay mang kỳ `FY<năm>` từ tiêu đề ô, mặc định FY2025.
- **CAGR đọc nhầm năm:** "Tăng trưởng kép 2018–2025: 16,5%" thành 2018. Nay lấy số đứng trước `%`; câu chunk ghi "tăng trưởng kép (CAGR) 2018–2025: 16,5%".
- **Verifier chặn nhầm:** năm/ngày chép từ câu hỏi không có trong chunk; "tăng" trên ô KPI cần chủ ngữ khớp tuyệt đối. Nay service nạp fact SQL của các chunk được trích (`Context.chunk_facts`), kỳ của fact chứng nhận năm/ngày, mũi tên KPI chứng nhận chiều; "tăng trưởng kép" là tên chỉ tiêu.
- **Generator** tự tính lại mức thay đổi đã công bố (`growth(a=fact %, b=None)`): dòng fact nay hiện `chiều: tăng/giảm`, prompt yêu cầu dẫn thẳng mức thay đổi đã công bố.
- **Eval dev lần 1** chặn 32% claim. Thêm ba quy tắc hẹp, vẫn gắn chủ ngữ: ô % có dấu tường minh ("+18,16%") cho fact chiều; từ chỉ chiều không kèm số được trích nguyên văn (khung 5 từ) từ chunk thì qua; dòng tiền chi ra trong ngoặc đọc theo độ lớn. Cách gắn chiều chỉ theo con số đã thử và bỏ: bộ adversarial bắt được "Tổng tài sản giảm 0,5%" mượn chiều của CIR.

Sau sửa: 10/10 câu mẫu đúng; dev (25 câu): claim bị chặn 32% → 18,5%, citation_hit 0,36 → 0,45, refusal_ok 0,60 → 0,72, unit_ok 0,58 → 0,74, Recall@8 0,77, MRR 0,64.

Còn mở: own-07, own-40 (không truy hồi được); own-22, own-29 (`number_mismatch`); own-35 (`evidence_not_substring`); own-09 (chặn an toàn vì "TCBS" không có trong ngữ cảnh ô KPI); own-45 ("hôm nay"), own-47 ("riêng lẻ") trả lời thay vì từ chối; own-42 lấy ưu tiên của khối CIB. Một số câu đúng số nhưng trích trang khác gold (own-01 tr. 14 thay vì 48, own-15, own-21, own-31): gold cần thêm trang thay thế.
