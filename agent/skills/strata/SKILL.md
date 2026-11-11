---
name: strata
description: Sổ tay dùng app Strata (SQLite + CLI strata.py + viewer http://127.0.0.1:8740) để ghi/đọc task, issue, doc, sơ đồ C4 và flow của bất kỳ project nào. Dùng khi user nhắc "strata", "ghi task", "tạo issue", "đổi trạng thái task", "vẽ C4", "sửa map", "flow", "viết doc", "project add", "viewer 8740", "strata.db".
---

# Strata

Strata giữ kiến thức project trong **một file SQLite** (mặc định `/home/abel/project/tools/strata/strata.db`, đổi bằng env `STRATA_DB` hoặc `--db`).
Ghi qua CLI `python3 /home/abel/project/tools/strata/strata.py`. Đọc qua web chỉ-GET http://127.0.0.1:8740
(systemd user `strata.service`; sửa Python thì `systemctl --user restart strata`, đổi dữ liệu chỉ cần reload trang).

```bash
S="python3 /home/abel/project/tools/strata/strata.py"   # dùng $S ở mọi lệnh dưới
```

## Bước 0: chọn project
```bash
$S project list
$S project add ID --name "Tên" --root /đường/dẫn/code --docs-dir /đường/dẫn/docs [--parent CHA] [--description "..."]
```
Hiện có: `internproj`; `project1_app` (cha internproj, root `/home/abel/project/internproj/project1_app`, docs `…/project1_app/documentation`); `strata` (docs `/home/abel/project/tools/strata/docs`).

## Muốn làm X → lệnh
| Muốn | Lệnh |
|---|---|
| Dựng project | `strata init [PATH] [--id --name --docs-dir --no-codemap --db-only]` (project, docs, map C4 mẫu, code map; chạy lại không hỏng) |
| Mở viewer | `strata open [PATH] [--port 8740]` (tìm project chứa PATH, mở trình duyệt; báo lỗi nếu chưa init hoặc viewer chưa chạy) |
| Danh sách project | `curl -s localhost:8740/api/projects` (Host phải là `127.0.0.1:8740` hoặc `localhost:8740`) |
| Task/issue | `curl -s 'localhost:8740/api/items?project=P'` (lọc thêm `&kind=task\|issue`, `&status=...`, `&id=N`) |
| Doc | `curl -s 'localhost:8740/api/docs?project=P'`; một doc: `/api/doc?project=P&path=research/x.yaml` (kèm `errors`) |
| Tìm kiếm | `curl -s 'localhost:8740/api/search?q=từ+khoá&project=P'` |
| Thêm task/issue | `$S item add --project P --kind task --title "..." [--body "..." --priority high --status approved]` → in `ok: item N` |
| Đổi trạng thái | `$S item set N --status doing [--priority ...]` |
| Item list/ready | `$S item list [--project P --kind K --status S --owner O --ready --json]`; `$S item ready [--project P]` (việc nhận được ngay) |
| Item show/edit | `$S item show N` (kèm dep); `$S item edit N [--title --body --spec JSON --priority]` |
| Item claim/submit | coder: `$S item claim N --as coder` → `$S item submit N --as coder --note "..."` (doing → review) |
| Item approve/reject | main: `$S item approve N [--note]` (review → done; proposed → approved); `$S item reject N --note "..."` |
| Item rework/close | main: `$S item rework N --note "..."` (review → doing, trả coder); `$S item close N --note "..."` (open → done, vd issue). `approve` chỉ từ proposed/review, trạng thái khác báo ERROR |
| Item release | `$S item release N` (doing → approved, bỏ claim) |
| Item dep | `$S item dep add\|rm N DEP` (N phụ thuộc DEP) |
| Tìm kiếm (CLI) | `$S search Q [--project P --src item\|page\|doc --limit N]` |
| MCP server | `$S mcp --role main\|coder\|reviewer` (stdio) |
| Gắn item vào object C4 | `$S c4 link --project P --object OBJ --item N` (gỡ: `unlink`; xem: `c4 links --project P --object OBJ`) |
| Gói ngữ cảnh task | `$S task context ID [--budget 12000]` (ticket, luật cứng, c4, đường dẫn; quá ngân sách thì cắt, cảnh báo stderr) |
| Đọc map | `$S c4 context --project P [--object OBJ] [--max-tokens 2000]` |
| Đọc flow | `$S c4 flow --project P` (liệt kê) / `$S c4 flow --project P --id FLOW` |
| Sửa map | sửa thư mục `docs/c4` → `$S c4 validate docs/c4` (0 lỗi) → `$S c4 import docs/c4 --project P`. Chi tiết: `docs/AGENT_C4.md` |
| Code map | `$S code snapshot --project P [--reindex]` (GitNexus quét code → `<db>.codemap/P.json`; `--reindex` chạy `analyze --index-only` trước); xem ở tab Code map (viewer `#/p/P/codemap`). GitNexus nằm ở `tools/gitnexus` (`fetch.sh`; `npm install` cần user duyệt) |
| Đọc contract | `$S c4 contract ID --project P` |
| Viết tài liệu | file YAML trong `<docs_dir>/research\|architect\|plan\|review/`, server tự quét. Định dạng: `docs/architect/doc-format.yaml` |
| Kiểm tra doc | `$S doc validate FILE` |
| Quét doc tay | `$S doc scan --project P` |
| Gán feature/status doc | `$S doc set --project P research/x.yaml --feature F --status current\|draft\|outdated\|missing [--ord N]` |
| Page JSON | `$S page validate F.json` / `$S page put F.json` / `$S page list [--project P]` |

Status item: `proposed|approved|open|doing|review|done|rejected` (mặc định `open`). Kind: `task|issue|step|gate`. Các chuyển trạng thái task hỗ trợ: approved → doing → review → done.

## Ví dụ doc tối thiểu (`<docs_dir>/research/vi-du.yaml`)
```yaml
title: So sánh cách lưu phiên        # bắt buộc
summary: Một câu cho mục lục
code: [src/session.py]
blocks:
  - md: |
      ## Bối cảnh
      Cần chọn nơi lưu phiên đăng nhập.
  - table:
      head: [Phương án, Ưu, Nhược]
      rows: [[Cookie, "đơn giản", "giới hạn 4KB"], [Redis, "nhanh", "thêm dịch vụ"]]
  - question:
      q: Chọn phương án nào?
      options: [{label: Cookie}, {label: Redis, note: "nếu cần scale"}]
      recommend: Cookie
```
Block khác: `diagram`, `layers`, `swimlane`, `mermaid`, `legend`, `c4`, `query` (xem doc-format.yaml).
Kiểm lỗi: mở viewer (trang hiện khung lỗi) hoặc `curl -s 'localhost:8740/api/doc?project=P&path=...' | jq .errors`.

## MCP
Ba server cùng `strata.py mcp --role ...`, khác nhau ở tập tool theo vai:
- `strata` (`--role main`): chat chính, đủ tool ghi.
- `strata-coder` (`--role coder`): đọc, `item_claim`/`item_submit`, thêm issue (`proposed`).
- `strata-reviewer` (`--role reviewer`): đọc, thêm issue (`proposed`).

Có MCP thì dùng MCP, không cần đọc bảng lệnh ở trên: server tự gửi hướng dẫn theo vai lúc kết nối, mỗi tool và tham số có mô tả.

| Muốn | Tool |
|---|---|
| Xem bảng việc | `list_items` (dòng gọn, không body; `ready=true` = nhận được ngay) → `get_item` |
| Bắt đầu một task | `task_context` → `item_claim` → làm → `item_submit` (cùng `actor`) |
| Duyệt / trả lại / đóng (main) | `item_approve`, `item_rework`, `item_close`, `item_reject`, `item_reopen`, `item_release` |
| Thêm / sửa | `add_item`, `edit_item`, `dep_add`, `dep_rm`, `c4_link` |
| Tài liệu, kiến trúc | `list_docs` → `get_doc`; `c4_context`, `c4_flow`; `search`; `audit` |

- `project` bỏ trống thì lấy project chứa thư mục làm việc của server (riêng `list_items`, `search`: bỏ trống = mọi project).
- Gọi sai thì lỗi nói rõ cách sửa: tên tham số lạ, thiếu tham số, giá trị ngoài enum, project không tồn tại (kèm danh sách), và với chuyển trạng thái: item đang ở đâu, vai này làm tiếp được gì.
- Kết quả bị cắt ở 8000 ký tự; thu hẹp bằng bộ lọc.

Cài đặt MCP: `claude mcp add --scope user strata -- python3 /home/abel/project/tools/strata/strata.py mcp --role main` (Codex: thay `claude` bằng `codex`, bỏ `--scope user`). Quyền từng role do server thực thi; quy trình agent thuộc `agent/` của Strata, không thuộc công cụ Strata. Sửa `strata/mcp.py` xong phải kết nối lại MCP (`/mcp`) hoặc mở phiên mới.

## Lỗi hay gặp (thư mục C4)
- Chuỗi có `:` `?` `{` `}` `,` `#` phải bọc `"..."`; dấu phẩy không bọc cắt chuỗi, `c4 validate` báo `key lạ`.
- Giữ `id` ổn định: link item và flow bám theo id; `c4 import` là upsert và **xoá** phần không còn trong thư mục.
- Phản hồi dùng `{link: id, reverse: true}`, không tạo link ngược.
- Flow phải liền mạch; `c4 validate` cảnh báo `đứt mạch` khi bước sau không nối bước trước.
- Cha hợp lệ: app/store → system/group; component → app/group; file/function → component/file.
