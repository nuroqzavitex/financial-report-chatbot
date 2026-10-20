# ADR 0021: OpenAI cho cả LLM và embedding, qua LiteLLM

- Trạng thái: Chấp nhận (2026-10-16, D21; thay quyết định bge-m3 local của DESIGN.md). Phần embedding đã được thay bằng ADR 0022 (2026-10-20); phần LLM vẫn giữ.

## Bối cảnh

DESIGN.md dùng bge-m3 chạy local cho embedding. Người chấm phải tải model vài GB và cài thêm phụ thuộc nặng trước khi chạy được. Bài nộp cần chạy trên máy sạch bằng một lệnh. Generator cần structured outputs strict (JSON schema), và đề cho phép dùng bất kỳ provider nào miễn là cấu hình được.

## Quyết định

- LLM và embedding đều gọi qua LiteLLM, mặc định OpenAI: một `OPENAI_API_KEY` là đủ cho mọi thứ.
- Embedding: `openai/text-embedding-3-large` với `dimensions=1024`, cosine. Cache theo `sha256(text) + model + dimensions` (`EMBED_CACHE_DIR`).
- Vector dense của `index/` được thiết kế để tính sẵn và ship cùng repo; `index/manifest.json` ghi `embed_model` và `embed_dimensions`. **Hiện `index/` chưa được build và commit** (cần `OPENAI_API_KEY`, môi trường làm bài không có); build bằng `uv run ircb ingest <pdf>`.
- Khởi động (`ircb chat`, `ircb batch`, `ircb index load`) so manifest với `EMBED_MODEL` / `EMBED_DIMENSIONS`: lệch thì in một dòng nêu lệnh `ircb index reembed` và thoát mã 1 (không traceback); thiếu `index/` thì in một dòng nêu lệnh `ircb ingest`.
- Đổi provider embedding: đặt `EMBED_MODEL` / `EMBED_DIMENSIONS` rồi chạy `ircb index reembed` (chỉ chạy lại bước embed, có cache, chi phí thấp).
- Sparse BM25 tự tính trong code (tokenizer tiếng Việt), không phụ thuộc provider.

## Hệ quả

- Người chấm chỉ cần một key, không tải model, chạy được trên laptop.
- Index khóa vào provider embedding; bù bằng manifest và `ircb index reembed`.
- Chạy offline hoàn toàn cần Ollama cho LLM và một embedding tương thích, rồi `reembed`.
- Đánh đổi: có chi phí API cho mỗi lần build/reembed và mỗi query embedding; có phụ thuộc mạng.

## Phương án đã cân nhắc

- **bge-m3 local:** không tốn API, nhưng phải tải model, chậm trên CPU, người chấm thêm một bước cài đặt. Bị loại cho đường chạy mặc định.
- **Anthropic cho LLM:** không có API embedding, vẫn cần provider thứ hai. Dùng được qua `LLM_MODEL=anthropic/...` nhưng không làm mặc định.
- **Gọi SDK OpenAI trực tiếp:** gắn cứng provider; LiteLLM giữ việc đổi provider chỉ là đổi biến môi trường.
