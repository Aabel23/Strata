# ⛰ Strata

Kiến trúc C4 viết dưới dạng code. Bạn mô tả hệ thống trong một file YAML, rồi xem nó qua một viewer có thể zoom qua các tầng.
Ý tưởng lấy từ IcePanel: **model trước, sơ đồ sau**.

Dữ liệu nằm trong SQLite (`$STRATA_DB`, hoặc `--db FILE`). YAML chỉ là định dạng nhập.

```
python3 strata.py import-yaml examples/project1_app.strata.yaml --project project1   # nạp vào DB (upsert, xóa phần đã bỏ)
python3 strata.py validate --project project1        # kiểm tra từ DB (hoặc: validate FILE.yaml)
python3 strata.py serve --project project1           # http://127.0.0.1:8740
```

Viewer cần server (`/api/c4`), không mở trực tiếp file HTML được nữa. Link tới code lấy gốc từ `root` trong YAML, đổi thành đường dẫn tuyệt đối lúc import.
Nhúng: `/c4?project=P&focus=<id>&embed=1` (zoom vào object, ẩn khung điều khiển).

## App shell nhiều project

`serve` mở `/` là app shell (chỉ đọc): sidebar cây project, tab Tổng quan / Task / Issue / Decision / Thảo luận / Tài liệu / Kiến trúc / Nhật ký, hash route `#/p/<project>/<tab>[/<id>]`, `Ctrl+K` tìm kiếm toàn văn (item, decision, page, doc). Mọi ghi dữ liệu đi qua CLI và để lại một dòng `audit`.

```
python3 strata.py project add ID --name N [--root DIR --docs-dir DIR --parent P --description T]   # docs-dir tương đối tính từ root
python3 strata.py project list
python3 strata.py doc scan --project P                  # quét docs_dir/*.html (bỏ assets/, plan/archive/, thư mục ẩn); file mất -> status missing
python3 strata.py doc set --project P PATH [--feature X --status current|draft|outdated|missing --ord N]
python3 strata.py item add --project P --kind task|issue --title T [--body --priority --status]
python3 strata.py item set ID [--status S --priority X]
```

`doc.kind` lấy từ thư mục đầu (`research|architect|review|plan`, còn lại `other`). Tiêu đề lấy từ `<title>` hoặc `<h1>`.

Route (GET): `/` shell, `/c4` viewer C4, `/pages`, `/page/<p>/<slug>`, `/api/projects` (kèm số đếm), `/api/items?project=&kind=&status=&id=`,
`/api/decisions?project=`, `/api/docs?project=`, `/api/audit?project=&limit=`, `/api/search?q=&project=` (FTS, bm25, tối đa 30),
`/docs/<project>/<path>` (phục vụ cả cây `docs_dir`; chặn `..`, dotfile, `.db`). Giá trị lọc ngoài whitelist trả 400.

## Tầng C4

| type | Tầng | Được nằm trong |
|---|---|---|
| `actor`, `system` | 1 Context | top level, `group` |
| `app`, `store` | 2 Container | `system` |
| `component` | 3 Component | `app` |
| `group` | gom nhóm (domain) | bất kỳ |

Tầng 4 không vẽ. Mỗi object có `links:` trỏ tới file code thật, và lệnh `validate` báo link nào đã chết.

## Model

```yaml
name: ...
root: đường/dẫn/tới/repo      # gốc của links, tính từ vị trí file model
tags: {security: {color: "#f04438"}}
objects:
  - {id, type, name, parent?, technology?, description?, tags?, links?, status?}
connections:
  - {id?, from, to, name?, technology?, status?, direction?: outgoing|bidirectional|none, tags?}
flows:
  - {id, name, steps: [{connection: id, text}]}
```

## Viewer

- **Zoom:** bấm đúp vào object có dấu ⊕ để zoom vào. Breadcrumb hoặc phím `Esc` để đi lên.
- **Lower connection:** connection ở tầng sâu tự hiện lên tầng trên, nối giữa hai object cha. Nhiều connection trùng hướng được gộp thành "N kết nối".
- **Object bên ngoài:** object ngoài phạm vi đang xem có viền nét đứt.
- **Status:** `future` vẽ nét đứt, `deprecated` màu cam, `removed` màu đỏ chấm.
- **Tag:** làm mờ những object không có tag đang chọn.
- **Flow:** tab *Diagram flows* ở panel phải; Previous/Next, bấm vào bước, hoặc phím mũi tên.
- **Canvas:** kéo để pan, lăn chuột để zoom, `F` vừa khung, `+`/`-` zoom. Nút ◐ đổi sáng/tối.

Thư viện bên thứ ba nằm trong `viewer/vendor/` (không dùng CDN): `dagre.min.js` 0.8.5, `mermaid.min.js` 10.9.1 (UMD, tải từ cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/).

## Page (tài liệu dạng block)

Page là một dòng trong bảng `page` (project, slug, title, kind `research|discussion|note`, blocks JSON). Nội dung chữ được đưa vào FTS (`search`, src=`page`).
File page là JSON `{project, slug, title, kind, blocks}`; xem `examples/strata-design.page.json`.

8 loại block (đúng 8, không thêm):

| type | trường |
|---|---|
| `md` | `text` (đoạn, `#`..`###`, danh sách, ``` code, `code`, **đậm**, link) |
| `layers` | `rows: [{title, cells: [{name, note?, status: done\|plan}]}]` |
| `mermaid` | `code` |
| `table` | `head: [..]`, `rows: [[..]]` |
| `legend` | `items: [{label, status: done\|plan}]` |
| `question` | `q`, `options: [{label, note?}]`, `recommend?` (trùng một label) |
| `c4` | `project?`, `ids: [..]` (nhúng viewer; id thiếu trong DB chỉ cảnh báo) |
| `query` | `src: item\|decision`, `where: {cột: giá trị}` (cột trong whitelist), `limit?` 1..200 |

```
python3 strata.py page validate FILE.json     # exit 1 nếu lỗi, vd "block[3] type layers: missing 'rows'" (block đánh số từ 0)
python3 strata.py page put FILE.json          # validate rồi upsert
python3 strata.py page list [--project P]
```

URL khi `serve`: `/pages[?project=P]` (danh sách), `/page/<project>/<slug>`, `/api/pages`, `/api/page/<p>/<s>`, `/api/page/<p>/<s>/version`,
`/api/query?src=item&project=..&status=..` (cột whitelist, sai cột trả 400), `/vendor/*`. Trang tự cập nhật (hỏi `/version` mỗi 2 giây).

## Ghép vào workflow

1. Đặt file `*.strata.yaml` trong repo cạnh code, ví dụ `documentation/architecture.strata.yaml`.
2. Agent architect cập nhật file này khi thiết kế thay đổi. Diff đọc được trong git.
3. Chạy `strata.py import-yaml` rồi `strata.py validate --project P` (hoặc `validate FILE`) trong CI hoặc pre-commit để bắt link chết và connection sai.
