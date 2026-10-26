# Strata: tài liệu kỹ thuật và sử dụng cho agent

Strata là công cụ quản lý task, issue, tài liệu và C4. Luật và quy trình agent dùng chung nằm trong `agent/`: [`agent/BOOTSTRAP.md`](agent/BOOTSTRAP.md), [`agent/HIEN_PHAP.md`](agent/HIEN_PHAP.md). Sổ tay dùng công cụ là [`agent/skills/strata/SKILL.md`](agent/skills/strata/SKILL.md).

## Tài liệu tham chiếu

- `docs/architect/ARCHITECTURE.md`: cấu trúc code, nguyên tắc.
- Vẽ/sửa C4 hoặc flow: `docs/AGENT_C4.md`.
- Viết tài liệu: `docs/architect/doc-format.yaml`.

## Kiến trúc và kiểm chứng

1. **Ghi qua service có kiểm tra và audit.** CLI/MCP là đường ghi chung. Viewer và server HTTP chỉ đọc, BỐN NGOẠI LỆ: `POST /api/c4/edit` (tab Architect): sửa thư mục YAML C4 của project qua service (kiểm như `c4 validate`, ghi vào thư mục, rồi import có audit); `POST /api/project` (op `add|edit|delete` từ sidebar, qua service có audit; `delete` là xoá cứng dòng trong DB, không đụng file, bắt buộc gõ lại id để xác nhận và tự sao lưu DB trước); `POST /api/item` (op `add|edit|delete|dep_add|dep_rm` trên task/issue, qua service có audit; sửa được mọi trường: title, body, status, priority, deps, spec goal/acceptance/verify/scope; `delete` là xoá cứng, có audit); và `POST /api/chat` (chat AI, op `start|turn|decide|cancel|close|login|cancel_login`; không ghi DB/audit, chỉ điều khiển phiên Codex cục bộ; `start` nhận project id đã đăng ký trong DB, không nhận đường dẫn từ trình duyệt; `start` tạo một git worktree riêng trên đĩa dưới `.strata-worktrees/` cạnh project, và phiên chạy với cwd là worktree đó; không có guard đường dẫn riêng, ranh giới là sandbox `read-only` + duyệt từng hành động qua `decide` + cwd worktree; khoá API chỉ lấy từ môi trường server, chỉ vào env của tiến trình codex app-server (`OPENAI_API_KEY`), bị `shell_environment_policy` lọc khỏi tiến trình con chạy lệnh/tool, và không bao giờ tới trình duyệt). Kèm 3 route đọc `GET /api/chat/events`, `GET /api/chat/auth`, `GET /api/chat/diff`: bắt buộc `X-Strata-Token` và kiểm Host, không ghi DB/audit (`auth` chạy codex, `diff` chạy git). Mọi route ghi (cả bốn) phải qua: cờ `allow_edit` (mặc định chỉ khi bind loopback), header `X-Strata-Edit: 1`, token ngẫu nhiên mỗi lần khởi động gửi trong header `X-Strata-Token`, cộng kiểm Origin/Host sẵn có. Không có route POST/PUT/DELETE nào khác.
   - Bảng `doc` là chỉ mục dẫn xuất từ file; server autoscan được làm mới nó, không ghi audit.
   - Bản đồ C4 là thư mục layered (`docs/c4`); sửa file rồi `c4 import`; sửa từ viewer chỉ đi qua route `POST /api/c4/edit` nói trên. SQLite chỉ là read model của thư mục đó.
2. **Không phụ thuộc nặng.** Python stdlib + PyYAML; JS thuần, không build, không CDN.
   - Ngoại lệ có phạm vi: `tools/gitnexus` là công cụ Node vendored cho agent, chỉ gọi qua CLI/subprocess, code Strata không bao giờ import nó; lõi vẫn là Python stdlib + PyYAML và JS thuần.
3. **Tài liệu chỉ nội dung.** Agent viết YAML theo `doc-format.yaml`; không tự viết HTML/CSS/JS cho tài liệu. Framework lo trình bày.
4. **Kiểm chứng thay đổi ứng dụng: chạy test, restart, mở viewer.** `systemctl --user restart strata`, cổng 8740. Sửa CSS/JS thì nhắc Ctrl+Shift+R.
5. Test: `venv/bin/python -m pytest -q` (venv ở gốc repo). Báo đúng số pass/fail.

## Thư mục `agent/`

`agent/` chứa luật, vai agent, quy trình, hook và skill dưới dạng file thật (đã gộp từ Endo); đây là nguồn chuẩn và nơi sửa chính sách. [`agent/skills/strata/SKILL.md`](agent/skills/strata/SKILL.md) là sổ tay công cụ. `agent/skills/schematic/` là skill bên thứ ba, cố ý nằm ngoài git.
