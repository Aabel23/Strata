# Strata: quy ước cho agent làm trong repo này

Luật chung (HIEN_PHAP, luồng 6 bước) đã nạp qua `agent/BOOTSTRAP.md`. File này chỉ thêm luật riêng của Strata.

## Đọc trước khi sửa

- `HANDOVER.md`: trạng thái, việc dở.
- `docs/architect/ARCHITECTURE.md`: cấu trúc code, nguyên tắc.
- Vẽ/sửa C4 hoặc flow: `docs/AGENT_C4.md`.
- Viết tài liệu: `docs/architect/doc-format.yaml`.

## Luật cứng

1. **Ghi qua service có kiểm tra và audit.** CLI/MCP là đường ghi chung. Viewer và server HTTP chỉ đọc, BA NGOẠI LỆ: `POST /api/c4/edit` (tab Architect): sửa thư mục YAML C4 của project qua service (kiểm như `c4 validate`, ghi vào thư mục, rồi import có audit); `POST /api/project` (op `add|edit|delete` từ sidebar, qua service có audit; `delete` là xoá cứng dòng trong DB, không đụng file, bắt buộc gõ lại id để xác nhận và tự sao lưu DB trước); và `POST /api/item` (op `add|edit|delete|dep_add|dep_rm` trên task/issue, qua service có audit; sửa được mọi trường: title, body, status, priority, deps, spec goal/acceptance/verify/scope; `delete` là xoá cứng, có audit). Mọi route ghi (cả ba) phải qua: token ngẫu nhiên mỗi lần khởi động gửi trong header `X-Strata-Token`, cộng kiểm Origin/Host sẵn có. Không có route POST/PUT/DELETE nào khác.
   - Bảng `doc` là chỉ mục dẫn xuất từ file; server autoscan được làm mới nó, không ghi audit.
   - Bản đồ C4 là thư mục layered (`docs/c4`); sửa file rồi `c4 import`; sửa từ viewer chỉ đi qua route `POST /api/c4/edit` nói trên. SQLite chỉ là read model của thư mục đó.
2. **Không phụ thuộc nặng.** Python stdlib + PyYAML; JS thuần, không build, không CDN.
3. **Tài liệu chỉ nội dung.** Agent viết YAML theo `doc-format.yaml`; không tự viết HTML/CSS/JS cho tài liệu. Framework lo trình bày.
4. **Thiết kế giao diện phải nạp skill design trước** (`artifact-design` hoặc skill design user chỉ định), không tự làm.
5. **Sửa xong: chạy test, restart, mở viewer.** `systemctl --user restart strata`, cổng 8740. Sửa CSS/JS thì nhắc Ctrl+Shift+R.
6. Test: `/tmp/claude-1000/v/bin/python -m pytest -q` (venv tạo lại theo `HANDOVER.md` nếu mất). Báo đúng số pass/fail.

## Thư mục `agent/`

Nguồn gốc luật, skill, hook cho **mọi** phiên agent trên máy (không chỉ Strata). Xem `agent/BOOTSTRAP.md`. Sửa ở đây là đổi hành vi toàn cục: commit riêng, ghi rõ luật nào đổi.
