# ADR 0023: Embedding bằng qwen3-embedding:4b

- Trạng thái: Chấp nhận (2026-10-20; thay model của ADR 0022, giữ mọi phần còn lại)

## Bối cảnh

Dự án chạy hoàn toàn trên máy local, không deploy. Máy dev có GPU RTX 4060 8 GB, nên dùng được model embedding lớn hơn bản 0.6B mà vẫn chạy trên GPU.

## Quyết định

- `EMBED_MODEL=ollama/qwen3-embedding:4b`, giữ 1024 chiều: vector gốc 2560 chiều được Ollama cắt theo `dimensions` (model huấn luyện kiểu Matryoshka), nên kích thước index không đổi.
- `index/` được embed lại bằng model này (`index_version` `def472d744b6`, khoảng 1 phút trên GPU).

## Bằng chứng

Cùng 22 câu dev, dùng lại các câu viết lại đã trace (script so sánh chỉ chạy bước tìm kiếm, không gọi LLM), cùng chunk sau bản sửa chunking ngày 2026-10-20:

| Câu viết lại bằng | Model embedding | Recall@8 | MRR |
|---|---|---|---|
| `openai/gpt-4o` | 0.6b | 0,818 | 0,661 |
| `openai/gpt-4o` | 4b | 0,818 | 0,658 |
| `gpt-oss:120b` (LLM đang dùng) | 0.6b | 0,636 | 0,494 |
| `gpt-oss:120b` (LLM đang dùng) | 4b | 0,773 | 0,555 |

Với câu viết lại của gpt-oss, bản 4b tìm ra thêm 3 câu (own-19, own-21, own-29) và không câu nào tụt. Với câu viết lại của GPT-4o, bản 4b được own-19 nhưng mất own-31. Độ trễ embed một câu hỏi như nhau, khoảng 0,5 giây trên GPU.

## Hệ quả

- Cần `ollama pull qwen3-embedding:4b` (~2,5 GB), và 4,4 GB VRAM khi model được nạp.
- Không có GPU thì embed câu hỏi trên CPU chậm hơn bản 0.6B rõ rệt; khi đó quay lại 0.6B (`EMBED_MODEL=ollama/qwen3-embedding:0.6b`, rồi `ircb index reembed`).
- 22 câu là mẫu nhỏ: mỗi câu tương đương 0,045 Recall@8.
