# ADR 0019: Phép tính khai báo trong JSON, code thực thi và điền chỗ trống

- Trạng thái: Chấp nhận (2026-10-16, D19)

## Bối cảnh

Câu hỏi so sánh và tăng trưởng (ví dụ "tổng tài sản tăng bao nhiêu so với năm trước") cần số học trên các fact có đơn vị khác nhau (nghìn tỷ, tỷ, triệu đồng). Nếu LLM tự tính, nó có thể tính sai hoặc viết một con số nghe hợp lý nhưng không có trong nguồn. Gọi công cụ tính qua vòng tool thì tốn thêm vòng (ADR 0018) và phụ thuộc khả năng tool calling của model.

## Quyết định

Generator không viết kết quả phép tính. Nó khai báo trong JSON:

- `calcs`: danh sách phép tính (`diff`, `growth`, `ratio`, `convert`) với toán hạng chỉ có thể là `fact:<id>` hoặc `calc:<id>` (lồng tối đa một tầng).
- Trong câu chữ, model chỉ viết chỗ trống `{c1}`, `{c2}`.

Code (`answering/calc.py`) kiểm tra ràng buộc (cùng đơn vị hoặc quy đổi được, cùng chỉ tiêu cho phép trừ, cơ sở dương cho tăng trưởng), tính bằng `decimal.Decimal`, rồi điền giá trị đã định dạng kiểu Việt Nam, kèm **chiều tăng/giảm do code render**. Model không bao giờ nhìn thấy kết quả.

## Hệ quả

- Model không thể chép sai hay bịa kết quả vì nó không có kết quả để chép.
- Mọi phép tính truy vết được: toán hạng, công thức, trang nguồn (cho `CalcChip` và cho trace).
- Không tốn vòng tool, chạy được với model local.
- Đánh đổi: schema output phức tạp hơn; cần luật render chiều; verifier phải chặn từ chỉ chiều viết tay cạnh chỗ trống và số tính toán viết tay thay cho chỗ trống.

## Phương án đã cân nhắc

- **LLM tự tính trong câu trả lời:** dễ sai số học và sai thang đơn vị. Bị loại.
- **Công cụ `calculate()` gọi qua tool loop:** đúng số nhưng thêm vòng, thêm latency, và model vẫn thấy kết quả rồi có thể diễn đạt lại sai. Bị loại.
- **Model sinh biểu thức Python/`eval`:** bề mặt tấn công và khó kiểm soát đơn vị. Bị loại.
