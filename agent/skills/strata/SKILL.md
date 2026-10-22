---
name: strata
description: Sổ tay dùng app Strata (SQLite + CLI strata.py + viewer http://127.0.0.1:8740) để ghi/đọc task, issue, doc, sơ đồ C4 và flow của bất kỳ project nào. Dùng khi user nhắc "strata", "ghi task", "tạo issue", "đổi trạng thái task", "vẽ C4", "sửa map", "flow", "viết doc", "project add", "viewer 8740", "strata.db"; hoặc khi đi qua bước 2 (sơ đồ), 3 (research/doc), 4 (duyệt → task), 6 (lỗi → issue) của luồng làm việc.
---

# Strata

Strata giữ kiến thức project trong **một file SQLite** (mặc định `/home/abel/project/tools/strata/strata.db`, đổi bằng env `STRATA_DB` hoặc `--db`).
Ghi qua CLI `python3 /home/abel/project/tools/strata/strata.py`. Đọc qua web chỉ-GET http://127.0.0.1:8740
(systemd user `strata.service`; sửa Python thì `systemctl --user restart strata`, đổi dữ liệu chỉ cần reload trang).

```bash
S="python3 /home/abel/project/tools/strata/strata.py"   # dùng $S ở mọi lệnh dưới
```

## Luật
- Chỉ **agent chính** ghi (ngoại lệ: coder/reviewer qua MCP theo vai, xem mục MCP). Subagent không có MCP thì trả văn bản cho agent chính ghi.
- Không sửa DB bằng `sqlite3` trực tiếp. Không tự viết HTML cho tài liệu (viết YAML, Strata lo trình bày).
- Thử lệnh ghi lạ trên DB tạm: `$S init --db /tmp/x/t.db` rồi thêm `--db /tmp/x/t.db`.

## Bước 0: chọn project
```bash
$S project list
$S project add ID --name "Tên" --root /đường/dẫn/code --docs-dir /đường/dẫn/docs [--parent CHA] [--description "..."]
```
Hiện có: `internproj`; `project1_app` (cha internproj, root `/home/abel/project/internproj/project1_app`, docs `…/project1_app/documentation`); `strata` (docs `/home/abel/project/tools/strata/docs`).

## Muốn làm X → lệnh
| Muốn | Lệnh |
|---|---|
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
| Roadmap import | `$S roadmap import PLAN.json [--progress P.json] [--gates "G0=0;G1=1,2"] --project P --roadmap ID` (gates: khoá `"gates"` trong plan, không có thì `--gates`, không có nữa thì 0 gate; gate bỏ khỏi plan mà chưa done → rejected) |
| Roadmap check/gate/reaccept | `$S roadmap check --project P --roadmap ID [--json]`; user: `$S roadmap gate pass G0 --project P --roadmap ID --as user [--evidence E]`; `$S roadmap reaccept STEP --project P --roadmap ID --as user` |
| Gói ngữ cảnh task | `$S task context ID [--budget 12000]` (ticket, luật cứng, c4, đường dẫn; quá ngân sách thì cắt, cảnh báo stderr) |
| Đọc map | `$S c4 context --project P [--object OBJ] [--max-tokens 2000]` |
| Đọc flow | `$S c4 flow --project P` (liệt kê) / `$S c4 flow --project P --id FLOW` |
| Sửa map | sửa thư mục `docs/c4` → `$S c4 validate docs/c4` (0 lỗi) → `$S c4 import docs/c4 --project P`. Chi tiết: `docs/AGENT_C4.md` |
| Đọc contract | `$S c4 contract ID --project P` |
| Viết tài liệu | file YAML trong `<docs_dir>/research\|architect\|plan\|review/`, server tự quét. Định dạng: `docs/architect/doc-format.yaml` |
| Kiểm tra doc | `$S doc validate FILE` |
| Quét doc tay | `$S doc scan --project P` |
| Gán feature/status doc | `$S doc set --project P research/x.yaml --feature F --status current\|draft\|outdated\|missing [--ord N]` |
| Page JSON | `$S page validate F.json` / `$S page put F.json` / `$S page list [--project P]` |

Status item: `proposed|approved|open|doing|review|done|rejected` (mặc định `open`). Kind: `task|issue|step|gate`. Luồng task: approved → doing → review → done.

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

## Luồng 6 bước → Strata
- **B2 sơ đồ**: viết/sửa thư mục C4 (map, contracts, flows) → `c4 validate` → `c4 import`.
- **B3 research**: mỗi research-stage là một doc YAML trong `<docs_dir>/research/` (chat chính ghi, theo skill `research-stage`).
- **B4 user duyệt**: `item add --kind task --status approved` + `c4 link` vào object liên quan.
- **B5 làm**: coder `item claim N --as coder` → `item submit N --as coder --note "..."`; main `item approve N`.
- **B6 lỗi**: `item add --kind issue` (+ `c4 link`).
- Ngoại lệ: `project1_app` vẫn dùng `documentation/plan/plan.json` cho luồng đang chạy.

## MCP
Ba server cùng `strata.py mcp --role ...`, khác nhau ở tập tool theo vai:
- `strata` (`--role main`): chat chính.
- `strata-coder` (`--role coder`): coder claim/submit.
- `strata-reviewer` (`--role reviewer`): reviewer đọc, thêm issue (`proposed`).
Đăng ký đang chờ user (xem "Cài đặt" trong `agent/BOOTSTRAP.md`). Có MCP thì ưu tiên MCP hơn CLI.

## Lỗi hay gặp (thư mục C4)
- Chuỗi có `:` `?` `{` `}` `,` `#` phải bọc `"..."`; dấu phẩy không bọc cắt chuỗi, `c4 validate` báo `key lạ`.
- Giữ `id` ổn định: link item và flow bám theo id; `c4 import` là upsert và **xoá** phần không còn trong thư mục.
- Phản hồi dùng `{link: id, reverse: true}`, không tạo link ngược.
- Flow phải liền mạch; `c4 validate` cảnh báo `đứt mạch` khi bước sau không nối bước trước.
- Cha hợp lệ: app/store → system/group; component → app/group; file/function → component/file.
