# ADR 0022: Embedding bằng qwen3-embedding:0.6b trên Ollama

- Trạng thái: Chấp nhận (2026-10-20; thay phần embedding của ADR 0021, giữ phần LLM)

## Bối cảnh

ADR 0021 dùng OpenAI `text-embedding-3-large` cho cả index lẫn câu hỏi. Khi tài khoản OpenAI hết credit, mọi câu hỏi mới đều lỗi ở bước tìm kiếm, kể cả khi LLM đã chuyển sang provider khác, vì câu hỏi phải được embed bằng đúng model của index. Ollama Cloud không có model embedding, nên không thay được OpenAI ở bước này.

## Quyết định

- `EMBED_MODEL=ollama/qwen3-embedding:0.6b`, 1024 chiều, cosine. Index và mọi câu hỏi đều được embed bằng cùng một server Ollama (`OLLAMA_API_BASE`): máy dev, và Ollama chạy kèm API khi deploy. Cùng phần mềm, cùng model nên vector câu hỏi khớp tuyệt đối với index.
- `index/` ship cùng repo được embed bằng model này (`index_version` `63623ba38ee1`, embed lại toàn bộ mất 3 phút 45 giây trên máy dev).
- LLM không đổi theo quyết định này: mặc định vẫn `openai/gpt-4o`; `ollama_chat/<model>-cloud` qua Ollama đã đăng nhập là tuỳ chọn không cần key.

## Bằng chứng

Cùng 22 câu dev đã được GPT-4o viết lại, chỉ đổi index (script so sánh chạy riêng bước tìm kiếm):

| Index | Recall@8 | MRR |
|---|---|---|
| `openai/text-embedding-3-large` | 0,773 | 0,666 |
| `ollama/qwen3-embedding:0.6b` | 0,773 | 0,655 |

## Hệ quả

- Không tốn chi phí và không cần mạng cho embedding; không phụ thuộc credit của một provider.
- Người chạy phải cài Ollama và `ollama pull qwen3-embedding:0.6b` (~640 MB). `scripts/smoke_test.sh` kiểm tra và thoát mã 4 nếu thiếu.
- Embed câu hỏi trên CPU mất khoảng 2 giây (p50 của `prefetch` trong dev eval), chậm hơn gọi API.
- Deploy cần thêm một Ollama bên cạnh API (~1,5–2 GB RAM), hoặc embed lại index bằng một API phục vụ cùng model rồi dùng API đó cho câu hỏi.

## Phương án đã cân nhắc

- **Gemini `gemini-embedding-001`:** gọn khi deploy, nhưng cần key và lại phụ thuộc một provider trả phí.
- **bge-m3 trên Ollama:** cũng chạy local, giấy phép MIT; Qwen3-Embedding được chọn vì điểm đa ngôn ngữ cao hơn và nhẹ hơn.
- **Giữ OpenAI:** chất lượng ngang (bảng trên) nhưng bị chặn khi hết credit.
