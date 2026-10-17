# ADR 0018: Không dùng agent loop, code lấy trước dữ liệu và LLM gọi một lần

- Trạng thái: Chấp nhận (2026-10-16, D18)

## Bối cảnh

Bản thiết kế đầu (`docs/DESIGN.md`) để LLM tự gọi `lookup_fact` và công cụ tính toán qua nhiều vòng tool. Với tài liệu này, đa số câu hỏi cần đúng thứ có thể đoán trước: vài chunk văn xuôi, một hoặc hai fact (chỉ tiêu × kỳ), và đôi khi một phép tính. Bài toán là phục vụ người dùng phân tích, chạy batch không người gõ, và phải đo được bằng eval.

## Quyết định

Code thực hiện toàn bộ bước lấy dữ liệu trước khi gọi model:

1. Period guard (xác định, không dùng LLM) chặn kỳ nằm ngoài tài liệu.
2. Rewriter cho ra `metrics[]` / `periods[]`.
3. Prefetch song song: hybrid chunks và `lookup_fact` cho mỗi cặp metric x period, một request embedding duy nhất.
4. Generator được gọi **một lần**, trả JSON gồm claims và phép tính khai báo.
5. Ngoại lệ có kiểm soát: model có thể trả `need_fact` để xin thêm fact, tối đa **một** vòng bổ sung (đo bằng `retrieval_recovered`).

## Hệ quả

- Latency thấp và dự đoán được: số lần gọi LLM cố định (rewriter + generator, hiếm khi thêm một lần).
- Eval ổn định hơn: không có quỹ đạo tool ngẫu nhiên, hai lần chạy khác nhau ít khi rẽ nhánh khác nhau.
- Quy lỗi rõ ràng theo từng bước (`I-extract`, `R-miss`, `G-wrong`, `V-blocked`) vì mỗi bước có trace riêng.
- Chạy được với model local không giỏi tool calling.
- Đánh đổi: kém linh hoạt với câu hỏi lạ mà rewriter không đoán đúng metric. Vòng `need_fact` chỉ bù một phần.

## Phương án đã cân nhắc

- **Agent loop đầy đủ (ReAct / tool calling nhiều vòng):** linh hoạt hơn nhưng latency và chi phí tăng theo số vòng, kết quả dao động giữa các lần chạy, khó biết lỗi do retrieval hay do việc chọn tool. Bị loại.
- **Không prefetch fact, chỉ RAG trên chunk:** bỏ qua fact store, mất lợi thế của việc trích xuất có cấu trúc. Bị loại.
