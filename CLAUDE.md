# Strata: quy ước cho agent làm trong repo này

Luật chung (HIEN_PHAP, luồng 6 bước) đã nạp qua `agent/BOOTSTRAP.md`. File này chỉ thêm luật riêng của Strata.

## Đọc trước khi sửa

- `HANDOVER.md`: trạng thái, việc dở.
- `docs/architect/ARCHITECTURE.md`: cấu trúc code, nguyên tắc.
- Vẽ/sửa C4 hoặc flow: `docs/AGENT_C4.md`.
- Viết tài liệu: `docs/architect/doc-format.yaml`.

## Luật cứng

1. **Ghi qua service có kiểm tra và audit.** CLI/MCP là đường ghi chung. Viewer được phép dùng đúng ba route POST C4 dưới đây; không thêm route ghi chung:
   - Bảng `doc` là chỉ mục dẫn xuất từ file; server autoscan được làm mới nó, không ghi audit.
   - `POST /api/c4/object`: create/update/move/delete object; legacy `fields` payload edits name/description/technology/status.
   - `POST /api/c4/port`: create/update/delete typed ports.
   - `POST /api/c4/link`: create/update/delete connections.
   All three require an allowed Host, same-origin Origin, JSON content type and bounded body. They validate and commit through `strata.service` with audit in one transaction. SQLite is the C4 source of truth; YAML is import/export only.
2. **Không phụ thuộc nặng.** Python stdlib + PyYAML; JS thuần, không build, không CDN.
3. **Tài liệu chỉ nội dung.** Agent viết YAML theo `doc-format.yaml`; không tự viết HTML/CSS/JS cho tài liệu. Framework lo trình bày.
4. **Thiết kế giao diện phải nạp skill design trước** (`artifact-design` hoặc skill design user chỉ định), không tự làm.
5. **Sửa xong: chạy test, restart, mở viewer.** `systemctl --user restart strata`, cổng 8740. Sửa CSS/JS thì nhắc Ctrl+Shift+R.
6. Test: `/tmp/claude-1000/v/bin/python -m pytest -q` (venv tạo lại theo `HANDOVER.md` nếu mất). Báo đúng số pass/fail.

## Thư mục `agent/`

Nguồn gốc luật, skill, hook cho **mọi** phiên agent trên máy (không chỉ Strata). Xem `agent/BOOTSTRAP.md`. Sửa ở đây là đổi hành vi toàn cục: commit riêng, ghi rõ luật nào đổi.
