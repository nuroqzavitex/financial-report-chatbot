# ircb: chatbot hỏi đáp Báo cáo thường niên Techcombank 2025

`ircb` trả lời câu hỏi (tiếng Việt, nhiều lượt) về một báo cáo thường niên 197 trang, mỗi câu trả lời có trích dẫn `[tr. N]` theo **số trang in**. Nguyên tắc chính: *LLM viết câu, code xác minh*. Số liệu, số trang, đơn vị và phép tính đều do code kiểm tra. Câu không có căn cứ bị từ chối, câu chỉ trả lời được một phần thì trả `partial`.

Thiết kế: [`docs/DESIGN.md`](docs/DESIGN.md). Bài nộp: [`SUBMISSION.md`](SUBMISSION.md). Nhật ký làm việc: [`docs/worklog.md`](docs/worklog.md). Quyết định kiến trúc: [`docs/adr/`](docs/adr/).

> **Trạng thái:** toàn bộ mã và test offline đã xong. Chưa có lần chạy nào với OpenAI API thật, nên `index/` **chưa được build và commit** và chưa có số liệu eval. Xem mục [Build index](#build-index) và `SUBMISSION.md`.

## Yêu cầu

- Python 3.11 (`uv` tự tải nếu máy chưa có)
- [uv](https://docs.astral.sh/uv/)
- `OPENAI_API_KEY` (mặc định dùng OpenAI cho cả LLM và embedding, không phải tải model nào)
- Docker: **không bắt buộc**, chỉ cho chế độ production local (bên dưới)

## Dữ liệu bảo mật: `data/`

`data/` nằm trong `.gitignore` và **không có trong repository**. Hãy tự đặt hai file được cung cấp vào đó, đúng tên:

```
data/techcombank-bao-cao-thuong-nien-2025-vie-update.pdf
data/sample_questions.json
```

PDF cần cho bước build index và cho các test golden (tự skip khi thiếu). Khi đã có `index/`, chat và batch chạy được mà không cần PDF.

## Chạy nhanh

Chế độ chấm bài: chỉ cần Python, không Docker (Qdrant embedded + SQLite).

```bash
export OPENAI_API_KEY=sk-...             # PowerShell: $env:OPENAI_API_KEY = "sk-..."
cp .env.example .env                     # LLM_MODEL mặc định openai/gpt-4o; key lấy từ môi trường hoặc điền vào .env
uv sync
# đặt PDF và sample_questions.json vào data/ (xem trên)
uv run ircb ingest data/techcombank-bao-cao-thuong-nien-2025-vie-update.pdf   # chỉ cần nếu index/ chưa có
uv run ircb chat
```

Kiểm tra từ máy sạch bằng một lệnh (venv tạm, `uv sync`, build index nếu thiếu, chạy 10 câu mẫu, khẳng định đủ 10 dòng và không dòng nào `error`):

```bash
export OPENAI_API_KEY=sk-...
bash scripts/smoke_test.sh               # in "OK 10/10"; thiếu data/ thì exit 2, thiếu key thì exit 3
```

Lần đầu `ircb chat` / `ircb batch` tự nạp `index/` vào `var/qdrant` và `var/app.db` (`AUTO_LOAD_INDEX=true`).

## Build index

`index/` là artefact ship cùng repo (chunks, facts, vector, `manifest.json`), nhưng **hiện chưa được commit** vì việc build cần OpenAI embedding API. Có `OPENAI_API_KEY` và PDF trong `data/` thì build bằng:

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
# OpenAI (mặc định): một key cho cả LLM và embedding
LLM_MODEL=openai/gpt-4o
OPENAI_API_KEY=sk-...

# Anthropic cho LLM; embedding vẫn là OpenAI nên vẫn cần OPENAI_API_KEY
LLM_MODEL=anthropic/claude-sonnet-4-5
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Local bằng Ollama (LLM và embedding); đổi embedding thì phải reembed
LLM_MODEL=ollama/qwen2.5:14b
OLLAMA_API_BASE=http://localhost:11434
EMBED_MODEL=ollama/nomic-embed-text
EMBED_DIMENSIONS=768
# rồi: uv run ircb index reembed
```

Lưu ý trung thực: đường chạy mặc định (OpenAI) là đường duy nhất được thiết kế và test; generator dùng structured outputs strict nên model khác có thể trả JSON lệch schema và dòng đó sẽ có `status="error"`. Cấu hình Anthropic và Ollama ở trên **chưa được chạy thử** (không có key hay Ollama trong môi trường làm bài), tên model chỉ là ví dụ. Nếu model không hỗ trợ `temperature=0` thì dùng `LLM_SEED` (mặc định 42). Chi phí chỉ được tính khi đặt `LLM_PRICE_IN` / `LLM_PRICE_OUT` (USD cho 1M token). Bảng đầy đủ các biến môi trường nằm ở `SUBMISSION.md` và `.env.example`.

## Hai chế độ chạy

Cùng một code, chọn bằng biến môi trường:

| | Chấm bài (mặc định) | Production local |
|---|---|---|
| Vector DB | Qdrant embedded (`QDRANT_PATH`, mặc định `./var/qdrant`) | Qdrant server (`QDRANT_URL`) |
| SQL | SQLite (`DATABASE_URL=sqlite:///./var/app.db`) | PostgreSQL |
| Docker | Không | Có (`docker-compose.yml`) |

Cả hai chế độ query Qdrant với `exact=True` nên top-k trùng nhau (có test tích hợp so sánh).

Chế độ production local (`docker-compose.yml` chỉ chứa Qdrant `:6333` và PostgreSQL `:5432`; CLI chạy trên máy host):

```bash
docker compose up -d --wait
export QDRANT_URL=http://localhost:6333
export DATABASE_URL=postgresql+psycopg://ircb:ircb@localhost:5432/ircb
uv run ircb index load --force
uv run ircb chat
docker compose down
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

## Cấu trúc

```
packages/core/src/ircb/   thư viện: domain, ingestion, retrieval, storage, llm, answering, service
apps/cli/src/ircb_cli/    lệnh `ircb` (typer): ingest, index, chat, batch, eval, profile
eval/                     dataset, runner chấm điểm, RAGAS, độ đồng thuận
config/                   sections.json, images.json, glossary_extra.json
docs/                     spec, ADR, worklog, mẫu SUBMISSION
scripts/                  profile_pdf.py, smoke_test.sh
```
