# ADR 0020: Verifier bỏ claim sai và trả `partial`

- Trạng thái: Chấp nhận (2026-10-16, D20)

## Bối cảnh

Verifier deterministic kiểm từng claim (số có trong nguồn, đúng đơn vị và thang, trang trích dẫn chứa claim, từ chỉ chiều khớp nguồn). Bản đầu từ chối cả câu khi có một claim fail. Câu hỏi kép (ví dụ giá trị cộng CAGR, hoặc một vế có trong tài liệu và một vế không) khi đó mất cả phần đúng, làm tỷ lệ từ chối nhầm cao.

## Quyết định

- Claim fail bị **loại**, claim pass được giữ.
- Còn ít nhất một claim: trạng thái `answered` nếu không claim nào bị loại, `partial` nếu có. Câu trả lời thêm một câu cố định "Chưa xác minh được một phần nội dung, xem [tr. N]." (chỉ số trang của các claim bị loại; không bao giờ lặp lại nội dung hay con số của claim bị loại).
- Generator tự báo `status: "partial"` (một vế không có nguồn) thì kết quả là `partial` dù mọi claim đều qua, kèm câu cố định "Một phần câu hỏi không có thông tin trong Báo cáo thường niên 2025."
- Ghi chú mâu thuẫn tự do của model (`conflict.note`) không bao giờ được hiển thị; chỉ giữ `conflict.kind` và renderer thêm một câu cố định theo loại (làm tròn / khác định nghĩa / khác thật sự, câu cuối có "cần kiểm tra").
- Hết claim: `refused`, kèm lý do và trang gợi ý.
- Verifier fail-closed: gặp đơn vị lạ, tiền tệ lạ, từ chỉ chiều không có tín hiệu hỗ trợ trong nguồn thì claim bị chặn.

## Hệ quả

- Giữ phần đúng của câu hỏi kép, giảm false refusal.
- Người dùng thấy rõ chỗ thiếu, không bị trả lời nửa vời một cách im lặng.
- Chặn nhầm là chấp nhận được (an toàn hơn bỏ lọt): kết quả là thêm câu `partial`; tỷ lệ này được đo trong eval (chỉ số vận hành: tỷ lệ `partial`, tỷ lệ chặn theo từng rule).
- Đánh đổi: câu trả lời có thể thiếu vế, người dùng phải đọc phần "chưa xác minh được".

## Phương án đã cân nhắc

- **Từ chối cả câu khi có claim fail:** đơn giản nhưng false refusal cao với câu kép. Bị loại.
- **Cho model tự sửa lại sau khi bị chặn (vòng retry):** thêm latency, kết quả dao động, và model có thể "sửa" bằng cách đoán. Bị loại.
- **Chỉ cảnh báo, vẫn hiện claim sai:** vi phạm nguyên tắc "người dùng không bao giờ thấy số chưa qua verifier". Bị loại.
