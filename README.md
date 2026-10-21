# ircb: chatbot hỏi đáp Báo cáo thường niên Techcombank 2025

`ircb` trả lời câu hỏi (tiếng Việt, nhiều lượt) về một báo cáo thường niên 197 trang, mỗi câu trả lời có trích dẫn `[tr. N]` theo **số trang in**. Nguyên tắc chính: *LLM viết câu, code xác minh*. Số liệu, số trang, đơn vị và phép tính đều do code kiểm tra. Câu không có căn cứ bị từ chối, câu chỉ trả lời được một phần thì trả `partial`.

Thiết kế: [`docs/DESIGN.md`](docs/DESIGN.md). Bài nộp: [`SUBMISSION.md`](SUBMISSION.md). Nhật ký làm việc: [`docs/worklog.md`](docs/worklog.md). Quyết định kiến trúc: [`docs/adr/`](docs/adr/).

> **Trạng thái:** toàn bộ mã và test offline đã xong. Chưa có lần chạy nào với OpenAI API thật, nên `index/` **chưa được build và commit** và chưa có số liệu eval. Xem mục [Build index](#build-index) và `SUBMISSION.md`.

## Yêu cầu

- Python 3.11 (`uv` tự tải nếu máy chưa có)
- [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com) và model embedding `qwen3-embedding:4b` (`ollama pull qwen3-embedding:4b`, ~2,5 GB). `index/` ship cùng repo được embed bằng model này, nên câu hỏi cũng phải được embed bằng chính nó
- Một LLM: mặc định `openai/gpt-4o` (cần `OPENAI_API_KEY`), hoặc model trên Ollama Cloud: `LLM_MODEL=ollama_chat/gemma4:31b` với `OLLAMA_API_BASE=https://ollama.com` và `OLLAMA_API_KEY` (cấu hình đã đo, xem `SUBMISSION.md`), hoặc qua Ollama local đã `ollama signin` (`ollama_chat/gemma4:31b-cloud`, không cần key)
- Docker: **không bắt buộc**, chỉ cho chế độ production local (bên dưới)

## Dữ liệu: `data/`

`data/` có sẵn trong repository: báo cáo thường niên (Techcombank công bố công khai) và 10 câu hỏi mẫu.

```
data/techcombank-bao-cao-thuong-nien-2025-vie-update.pdf
data/sample_questions.json
```

PDF cần cho bước build index và cho các test golden (tự skip khi thiếu). Khi đã có `index/`, chat và batch chạy được mà không cần PDF.

## Chạy nhanh

Chế độ chấm bài: chỉ cần Python, không Docker (Qdrant embedded + SQLite).

```bash
ollama pull qwen3-embedding:4b         # embedding, chạy local
cp .env.example .env                     # rồi điền OLLAMA_API_KEY (phần 1 của file); LLM mặc định gemma4:31b trên Ollama Cloud
uv sync
uv run ircb ingest data/techcombank-bao-cao-thuong-nien-2025-vie-update.pdf   # chỉ cần nếu index/ chưa có
uv run ircb chat
```

Kiểm tra từ máy sạch bằng một lệnh (venv tạm, `uv sync`, build index nếu thiếu, chạy 10 câu mẫu, khẳng định đủ 10 dòng và không dòng nào `error`):

```bash
bash scripts/smoke_test.sh               # in "OK 10/10"; thiếu data/ exit 2, thiếu key của LLM_MODEL exit 3, thiếu Ollama/model exit 4
```

Lần đầu `ircb chat` / `ircb batch` tự nạp `index/` vào `var/qdrant` và `var/app.db` (`AUTO_LOAD_INDEX=true`).

## Build index

`index/` là artefact ship cùng repo (chunks, facts, vector, `manifest.json`), embed bằng `ollama/qwen3-embedding:4b` 1024 chiều. Build lại từ PDF (cần Ollama với model trên):

```bash
uv run ircb ingest data/techcombank-bao-cao-thuong-nien-2025-vie-update.pdf          # ghi vào ./index
uv run ircb ingest data/techcombank-bao-cao-thuong-nien-2025-vie-update.pdf --out index
```

Pipeline gồm ba bước extract, normalize, embed (embed có cache theo hash trong `var/embed_cache`) và các cổng chất lượng (page map phải khớp, độ phủ bảng, mọi fact có đơn vị). Cổng nào fail thì lệnh thoát với mã 1, in lý do và đường dẫn `index/.tmp/ingest_report.json`. Build thành công ghi `index/manifest.json` (`index_version`, model embedding, số chunk và fact) cùng `ingest_report.json`. Thư mục trung gian `index/build/` bị gitignore; sau khi build xong, commit phần còn lại của `index/`.

Các lệnh index khác:

```bash
uv run ircb index load [--force]         # nạp index/ vào Qdrant + SQL (tự chạy lần đầu)
uv run ircb index reembed                # chạy lại riêng bước embed theo EMBED_MODEL hiện tại, rồi nạp lại hoàn toàn
uv run ircb profile data/<pdf>           # khảo sát cấu trúc PDF (M0)
```

## Đổi provider hoặc model

Mọi thứ đi qua LiteLLM, đổi bằng biến môi trường (hoặc `.env`). Đổi **embedding** thì phải chạy `uv run ircb index reembed` (manifest kiểm tra lệch lúc khởi động). Đổi riêng LLM thì không cần.

```bash
# Mặc định: embedding Qwen3 trên Ollama local, LLM OpenAI
EMBED_MODEL=ollama/qwen3-embedding:4b
LLM_MODEL=openai/gpt-4o
OPENAI_API_KEY=sk-...

# LLM trên Ollama Cloud bằng API key (https://ollama.com/settings/keys), tên model không có "-cloud";
# embedding vẫn chạy trên Ollama local (EMBED_API_BASE, mặc định http://localhost:11434)
LLM_MODEL=ollama_chat/gemma4:31b
OLLAMA_API_BASE=https://ollama.com
OLLAMA_API_KEY=...

# Không cần key: LLM trên Ollama Cloud qua Ollama local đã đăng nhập (`ollama signin`)
LLM_MODEL=ollama_chat/gemma4:31b-cloud
OLLAMA_API_BASE=http://localhost:11434

# Embedding OpenAI thay cho Qwen3 (đổi embedding thì phải reembed)
EMBED_MODEL=openai/text-embedding-3-large
OPENAI_API_KEY=sk-...
# rồi: uv run ircb index reembed
```

Đã chạy thật (dev eval, 25 câu): embedding Qwen3 tìm kiếm ngang OpenAI `text-embedding-3-large` (cùng câu hỏi đã viết lại: Recall@8 0,773 cả hai, MRR 0,655 so với 0,666). Với LLM, GPT-4o tốt hơn rõ: `gpt-oss:120b` qua Ollama Cloud làm bộ kiểm tra loại 44% ý (GPT-4o: 21%) và từ chối 13/25 câu (GPT-4o: 7/25). Generator dùng structured outputs strict nên model khác có thể trả JSON lệch schema và dòng đó sẽ có `status="error"`. Nếu model không hỗ trợ `temperature=0` thì dùng `LLM_SEED` (mặc định 42). Chi phí chỉ được tính khi đặt `LLM_PRICE_IN` / `LLM_PRICE_OUT` (USD cho 1M token). Bảng đầy đủ các biến môi trường nằm ở `SUBMISSION.md` và `.env.example`.

## Hai chế độ chạy

Cùng một code, chọn bằng biến môi trường:

| | Chấm bài (mặc định) | Production local |
|---|---|---|
| Vector DB | Qdrant embedded (`QDRANT_PATH`, mặc định `./var/qdrant`) | Qdrant server (`QDRANT_URL`) |
| SQL | SQLite (`DATABASE_URL=sqlite:///./var/app.db`) | PostgreSQL |
| Docker | Không | Có (`docker-compose.yml`) |

Cả hai chế độ query Qdrant với `exact=True`, và RRF được gộp phía client theo thứ tự cố định (điểm hòa xếp theo id), nên top-k trùng nhau (có test tích hợp so sánh trên tập dev).

### Chạy toàn bộ bằng Docker

`docker-compose.yml` dựng đủ bốn service: Qdrant `:6333`, PostgreSQL `:5432`, API `:8000`, web `:3000` (API và web chỉ mở trên `127.0.0.1`). Cần có sẵn trên máy: `.env` (ít nhất `LLM_MODEL` và key của nó), `index/` đã build và PDF trong `data/`. Hai thư mục này được mount read-only lúc chạy, không bao giờ nằm trong image.

```bash
docker compose up -d --build --wait      # lần đầu build image (~vài phút); API tự nạp index/ vào Qdrant + Postgres
# mở http://localhost:3000
docker compose logs -f api               # xem log API
docker compose down                      # dừng (giữ dữ liệu); thêm -v để xóa cả volume Qdrant/Postgres
```

- API đọc `.env` qua `env_file`; các biến kết nối (`QDRANT_URL`, `DATABASE_URL`, đường dẫn index/PDF/cache) do compose đặt sẵn.
- Web được build với `NEXT_PUBLIC_API_URL=http://localhost:8000` (địa chỉ trình duyệt gọi tới). Đổi cổng API thì sửa build arg trong `docker-compose.yml` rồi `docker compose build web`.
- Trace JSONL được ghi ra `./traces` trên máy host.

Chỉ dựng DB rồi chạy CLI trên máy host:

```bash
docker compose up -d --wait qdrant postgres
export QDRANT_URL=http://localhost:6333
export DATABASE_URL=postgresql+psycopg://ircb:ircb@localhost:5432/ircb
uv run ircb index load --force
uv run ircb chat
```

## Batch

```bash
uv run ircb batch data/sample_questions.json --out eval/reports/run.jsonl [--concurrency N]
```

Đầu vào là mảng JSON hoặc JSONL; dòng có `turns` được chạy như hội thoại nhiều lượt. Mỗi dòng đầu ra có `id`, `status` (`answered` | `partial` | `refused` | `error`), `answer`, `citations`, `claims`, `calcs`, `latency_ms` (theo từng bước), `cost_usd`, `trace_id`. Một dòng lỗi không làm dừng cả lần chạy. `--concurrency` mặc định 1 để đo latency chính xác. Trace từng câu nằm ở `TRACE_DIR` (JSONL, mặc định `./traces`).

## Eval

Bộ câu tự xây: `eval/datasets/own_questions.jsonl` (50 câu, 25 dev / 25 test). Bộ đối nghịch của verifier: `eval/datasets/adversarial.jsonl` (60 dòng; chạy như unit test trong suite, không cần API).

```bash
# trả lời tập dev bằng AnswerService rồi chấm (Recall@8, MRR, citation hit, refusal, unit, chỉ số vận hành)
uv run ircb eval --split dev --run
uv run ircb eval --split test --run      # chỉ chạy để báo cáo số cuối
# chấm lại một batch đã có, không gọi API
uv run ircb eval --split dev --batch-out eval/reports/batch_out.jsonl
```

Kết quả ghi vào `eval/reports/<timestamp>_<commit>.json` và phiếu chấm tay `eval/scoring/score_sheet.csv`. RAGAS (tùy chọn; `JUDGE_MODEL` nên khác `LLM_MODEL`) và độ đồng thuận với người chấm:

```bash
uv sync --group eval
uv run python eval/runners/ragas_eval.py --judge $JUDGE_MODEL --split dev
uv run python eval/runners/ragas_eval.py --judge $JUDGE_MODEL --adversarial eval/datasets/adversarial.jsonl
uv run python eval/runners/judge_agreement.py eval/scoring/score_sheet.csv eval/reports/ragas_<ts>.json
```

## API và Web

Lõi `ircb` có thêm một API FastAPI (`apps/api`, gói `ircb_api`) và một giao diện Next.js (`apps/web`). Cả hai chỉ là lớp mỏng: API gọi `AnswerService`, `PageRenderer`, `SqlFactStore`, `SessionRepo` và ánh xạ sang DTO; mọi kiểm tra số liệu vẫn nằm ở lõi. Claim bị verifier loại không bao giờ xuất hiện trong phản hồi. SSE chỉ stream trạng thái các bước, câu trả lời được gửi một lần sau khi verifier chạy xong.

```bash
# Terminal 1: API (cần index/ đã nạp và key của LLM_MODEL)
uv run uvicorn ircb_api.main:app --port 8000          # thêm --reload khi phát triển
# hoặc: uv run python -m ircb_api                      # chạy uvicorn trên API_HOST/API_PORT (mặc định 127.0.0.1:8000)

# Terminal 2: web (Node 20+, pnpm)
pnpm --dir apps/web install
cp apps/web/.env.local.example apps/web/.env.local     # NEXT_PUBLIC_API_URL=http://localhost:8000
pnpm --dir apps/web dev                                # http://localhost:3000
```

Sau khi đổi schema API, sinh lại kiểu TypeScript: `make gen-types` (không có `make`: `uv run python -m ircb_api.openapi apps/web/openapi.json` rồi `pnpm --dir apps/web gen:types`, xem `Makefile`).

**Trình xem trang cần PDF.** Ảnh trang in (có tô sáng vùng chứa con số) được render từ `data/…pdf` (`PDF_PATH`). Thiếu PDF thì `/v1/pages/{n}/image` trả HTTP 503 `{"code": "pdf_missing"}` và web hiển thị đoạn bằng chứng dạng chữ thay cho ảnh. Ảnh được cache ở `PAGE_CACHE_DIR` (`./var/page_cache`, không commit).

| Endpoint | Mô tả |
|---|---|
| `GET /v1/health` | Trạng thái, `index_version`, số chunk/fact, model, `pdf_available` |
| `POST /v1/chat` | Hỏi đáp; trả SSE: `status` (các bước) rồi `answer` rồi `done`, hoặc `error` |
| `GET /v1/sessions` | Các phiên của người gọi, mới nhất trước (tiêu đề là câu hỏi đầu) |
| `GET /v1/sessions/{id}` | Một phiên, kèm nguyên câu trả lời đã gửi (claim, trang, phép tính) |
| `DELETE /v1/sessions/{id}` | Xoá một phiên |
| `GET /v1/pages/{printed}/image?source=&evidence=` | PNG trang in số `printed`, tô sáng vùng bằng chứng |
| `GET /v1/facts?q=&period=&limit=` | Tra fact (giá trị là chuỗi Decimal) |
| `GET /v1/traces/{trace_id}` | Trace một câu; chỉ bật khi `APP_ENV=dev` |

**Lịch sử trò chuyện.** Web gửi header `X-Client-Id` (mã ngẫu nhiên lưu trong trình duyệt), nên mỗi trình duyệt chỉ thấy lịch sử của mình; mở phiên của người khác trả 404. Đây là tách lịch sử, chưa phải đăng nhập: ai có mã đó đều xem được các phiên ấy. Request không có header dùng chung một nhóm công khai.

**Đăng nhập (Clerk, tuỳ chọn).** Tạo application trên [Clerk](https://dashboard.clerk.com), rồi điền `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` và `CLERK_SECRET_KEY` vào `.env` (Docker đọc từ đây) và vào `apps/web/.env.local` (khi chạy `pnpm dev`). Khi có key, chat và lịch sử bắt buộc đăng nhập: web gửi session token của Clerk, API tự kiểm tra chữ ký bằng JWKS của Clerk, hạn dùng và origin (`CORS_ORIGINS`), và mỗi tài khoản chỉ thấy lịch sử của mình. Ảnh trang, tra fact và health vẫn công khai. Để trống hai key thì hệ thống chạy ẩn danh như trên. Đổi key thì build lại web (`docker compose up -d --build web`) vì publishable key được nhúng lúc build.

`/v1/traces` được bật khi `APP_ENV=dev` (mặc định), nên hãy đặt `APP_ENV=prod` trước khi bind API vào một host không phải máy cục bộ.

Biến môi trường: `API_HOST`, `API_PORT` (dùng bởi `python -m ircb_api`), `CORS_ORIGINS` (phân tách bằng dấu phẩy, mặc định `http://localhost:3000,http://127.0.0.1:3000`), `APP_ENV`, `PDF_PATH`, `PAGE_CACHE_DIR`; phía web: `NEXT_PUBLIC_API_URL`. Test web: `pnpm --dir apps/web test` (Vitest), `pnpm --dir apps/web e2e` (Playwright, API được mock), `pnpm --dir apps/web lint`, `pnpm --dir apps/web build`.

## Test và lint

```bash
uv run pytest                            # mặc định: không cần API, không cần Docker; test cần PDF tự skip khi thiếu data/
uv run pytest -m integration             # Qdrant server + Postgres thật (docker compose up -d --wait trước; tự skip nếu không kết nối được)
uv run ruff check .
uv run ruff format packages apps eval    # đừng chạy `ruff format .` ở root: nó định dạng lại code block trong docs/*.md
uv run mypy
uv run lint-imports                      # ircb không được import fastapi / ircb_cli / ircb_api
```

(`make setup | test | lint | ...` là bí danh của các lệnh trên nếu máy có `make`.)

## CI và image trên ghcr.io

`.github/workflows/ci.yml` chạy trên mỗi push và pull request:

- **python:** `ruff check`, `ruff format --check`, `mypy`, `lint-imports`, `pytest` (kể cả test golden trên PDF trong `data/`; không cần API key hay Ollama).
- **integration:** `pytest -m integration` với Qdrant `v1.19.0` và PostgreSQL 16 chạy dạng service container.
- **web:** `pnpm lint`, `pnpm test`, `pnpm build`.
- **publish:** chỉ khi push lên `main` hoặc tag `v*`, và cả ba job trên đều qua. Build và đẩy hai image lên GitHub Container Registry:
  - `ghcr.io/nuroqzavitex/financial-report-chatbot-api`
  - `ghcr.io/nuroqzavitex/financial-report-chatbot-web`

  Tag: `latest` và `sha-<commit>` cho `main`; `1.2.3` và `1.2` cho tag `v1.2.3`.

Image không chứa `index/` và `data/`: khi chạy vẫn mount hai thư mục này như trong `docker-compose.yml`. Image web được build với `NEXT_PUBLIC_API_URL=http://localhost:8000` và không bật Clerk (giá trị `NEXT_PUBLIC_*` được nhúng lúc build); muốn khác thì build lại bằng `docker compose build web`. Package mới trên ghcr.io mặc định là private: đổi sang public ở trang Packages của repo nếu muốn `docker pull` không cần đăng nhập.

## Cấu trúc

```
packages/core/src/ircb/   thư viện: domain, ingestion, retrieval, storage, llm, answering, service
apps/cli/src/ircb_cli/    lệnh `ircb` (typer): ingest, index, chat, batch, eval, profile
apps/api/src/ircb_api/    API FastAPI: routers, mapping.py (core sang DTO), SSE
apps/web/                 giao diện Next.js: chat, thẻ trả lời, trình xem trang
eval/                     dataset, runner chấm điểm, RAGAS, độ đồng thuận
config/                   sections.json, images.json, glossary_extra.json
docs/                     spec, ADR, worklog, mẫu SUBMISSION
scripts/                  profile_pdf.py, smoke_test.sh
```
