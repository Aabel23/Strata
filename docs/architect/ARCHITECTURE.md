# Kiến trúc Strata

Tài liệu cho người sửa code Strata. Cách dùng xem [README.md](../../README.md); agent vẽ map C4 xem [AGENT_C4.md](../AGENT_C4.md).

## 1. Tổng quan

Strata là công cụ cục bộ quản lý tri thức nhiều project: task/issue, decision, page dạng block, mục lục tài liệu HTML, bản đồ C4 và nhật ký audit. Tất cả nằm trong **một file SQLite**.

Nguyên tắc:

- **Ghi qua CLI, đọc qua web.** Server chỉ có `GET`. Mọi thay đổi dữ liệu đi qua `strata.py` và để lại dòng `audit`.
- **Model trước, sơ đồ sau.** C4 viết bằng YAML, nạp vào DB; viewer vẽ từ DB, không lưu toạ độ.
- **Không phụ thuộc nặng.** Python stdlib + PyYAML; JS thuần, không build, không CDN (thư viện ngoài nằm ở `viewer/vendor/`).

```
 YAML / JSON / docs_dir ──► strata.py (CLI) ──► SQLite ◄── strata/server.py (GET) ◄── trình duyệt (viewer/)
                                   │                                     ▲
                                   └──────── c4 context / flow ──► agent ┘ (văn bản gọn)
```

## 2. Cấu trúc thư mục

| Đường dẫn | Vai trò |
|---|---|
| `strata.py` | Điểm vào CLI (argparse), gọi xuống các module trong `strata/` |
| `strata/schema.sql` | Toàn bộ schema: bảng, trigger append-only, FTS5 |
| `strata/db.py` | Kết nối, `init` + migrate, CRUD project/doc/item/page/link, audit, `fold` cho tìm kiếm |
| `strata/c4.py` | Đọc/validate YAML, nạp vào DB (upsert + xoá phần bị bỏ), `read_model`, phát hiện issue, `context`, trace flow |
| `strata/blocks.py` | Validate 8 loại block của page |
| `strata/server.py` | HTTP server chỉ đọc: file tĩnh, `/api/*`, `/docs/*`, `/code/*` |
| `viewer/app.html`, `app.js`, `app.css` | App shell nhiều project (sidebar, tab, Ctrl+K, theme) |
| `viewer/index.html` | Viewer C4 (zoom theo tầng, flow, tag, tìm object) |
| `viewer/page.html`, `page.js`, `page.css` | Hiển thị page dạng block |
| `viewer/vendor/` | `dagre` (layout), `mermaid` |
| `viewer/assets/` | SVG trang trí phần đầu trang Tổng quan |
| `examples/` | Model C4 mẫu (`*.strata.yaml`), page mẫu (`*.page.json`) |
| `scripts/` | Công cụ phụ (trace ảnh hero sang SVG), không thuộc runtime |
| `tests/` | pytest, mỗi module một file |

## 3. Mô hình dữ liệu

Mọi bảng (trừ `project`) có cột `project`; khoá chính thường là `(project, id)`.

| Bảng | Nội dung | Ghi chú |
|---|---|---|
| `project` | id, name, root, docs_dir, parent | `parent` tạo cây project ở sidebar |
| `item` | task, issue, rule, knowledge, draft, note | `status`: proposed / approved / open / doing / done / rejected |
| `decision` | ADR: context, decision, consequences, rejected_options | **Append-only**: trigger chặn xoá và chỉ cho đổi `status`. Bắt buộc có `rejected_options` |
| `page` | slug, title, kind (research/discussion/note), `blocks` JSON | `text` là chữ trích ra để tìm kiếm |
| `doc` | mục lục file HTML trong `docs_dir` | `kind` theo thư mục đầu, `status` = missing khi file biến mất |
| `c4_meta` | tên model, `root` tuyệt đối, layout, định nghĩa tag | một dòng mỗi project |
| `c4_object` | actor, system, app, store, component, group, file, function | `parent` tạo cây; `links` trỏ file code |
| `c4_connection` | from → to, kind (network/call/queue), status, interface, payload | |
| `c4_interface` | hợp đồng gọi được của object: http/function/queue/event | |
| `c4_flow` | danh sách step JSON tham chiếu connection hoặc object | |
| `c4_link` | gắn object C4 với item/decision | |
| `audit` | ts, tool, target, before, after | mọi lệnh ghi đều thêm dòng |
| `search` | FTS5 trên item, decision, page, doc | trigger tự đồng bộ |

**Tìm kiếm tiếng Việt.** Tokenizer `unicode61 remove_diacritics 2` bỏ dấu, nhưng `đ` không tách được nên trigger đổi `đ→d`; câu truy vấn phải qua `db.fold` để đổi giống vậy.

**Migrate.** `db.init` chạy `ALTER TABLE ADD COLUMN` theo danh sách `ADDED`. Khi cần đổi `CHECK` (SQLite không sửa được), bảng cũ được đổi tên thành `*_old`, tạo lại, rồi chép dữ liệu sang. Thêm cột mới: thêm vào `schema.sql` **và** `ADDED`.

DB mặc định: `$STRATA_DB`, nếu không có thì `/home/abel/project/tools/strata/strata.db`. Mọi lệnh nhận `--db FILE`.

## 4. Luồng C4

1. **Đọc YAML** (`c4.read_yaml`): kiểm khoá hợp lệ theo `KEYS`, interface lồng trong object được tách ra.
2. **Validate**: type thuộc `TYPES`, cha hợp lệ theo `PARENTS`, id không trùng, connection/flow trỏ tới thứ tồn tại, kind/status hợp lệ.
3. **Nạp** (`import-yaml`): upsert từng object/connection/interface/flow, xoá những dòng không còn trong YAML, đổi `root` thành đường dẫn tuyệt đối.
4. **Phục vụ** (`/api/c4`): `read_model` + `issues_by_object` (`dead_link`, `no_link`, `no_desc`) + `links` + `open_issues`.
5. **Vẽ** (`viewer/index.html`): mỗi lần chỉ vẽ con trực tiếp của object đang zoom; connection ở tầng sâu được "nâng" lên nối giữa hai tổ tiên đang hiển thị và gộp nếu trùng hướng. Layout bằng dagre.

Cây cha–con hợp lệ:

| type | Tầng | Cha được phép |
|---|---|---|
| `actor`, `system` | L1 Context | top level, `group` |
| `app`, `store` | L2 Container | `system`, `group` |
| `component` | L3 Component | `app`, `group` |
| `file`, `function` | L4 Code | `component`, `file` |
| `group` | gom nhóm | top level, `group`, `system`, `app` |

**Cho agent.** `c4 context` in cây gọn có giới hạn token (ước `len/4`), cắt từ flow ngược lên khi vượt. `c4 flow --id F` in mỗi bước một dòng: `N. A → B [kind] text (interface) | payload: …`.

## 5. Server

`strata/server.py` dùng `http.server` stdlib, một connection SQLite dùng chung có khoá (`lock`).

Bảo vệ:

- **Chặn DNS rebinding:** header `Host` phải là `127.0.0.1:PORT` hoặc `localhost:PORT`, nếu không trả 403.
- **Chặn path traversal** ở `/docs/`, `/code/`, `/vendor/`, `/assets/`: resolve rồi kiểm `is_relative_to(root)`.
- **Ẩn file nhạy cảm:** dotfile, `*.db`, `*.sqlite*` trả 404.
- **Whitelist lọc:** `/api/items`, `/api/query` chỉ nhận cột/giá trị cho phép, sai trả 400.
- `/code/*` luôn trả `text/plain`.

Giới hạn đã biết: tài liệu HTML ở `/docs/` phục vụ cùng origin với app, không bị cô lập. Chỉ nên trỏ `docs_dir` vào tài liệu mình tin.

Page tự làm mới: `page.js` hỏi `/api/page/<p>/<s>/version` mỗi 2 giây (`updated_at` + `PRAGMA data_version`).

## 6. Mở rộng

- **Lệnh CLI mới:** thêm subparser trong `strata.py`, logic ở `strata/db.py` hoặc `strata/c4.py`, ghi `audit` nếu có ghi.
- **Trường C4 mới:** `KEYS` + validate trong `c4.py`, cột trong `schema.sql` + `ADDED` trong `db.py`, câu `INSERT … ON CONFLICT` khi nạp, rồi viewer.
- **API mới:** chỉ `GET`, giữ khoá `lock` khi đọc DB, lọc bằng whitelist.
- **Block page:** đang cố định đúng 8 loại; muốn thêm phải chốt với chủ project trước.

## 7. Chạy và kiểm thử

```
python3 strata.py init --db /tmp/x.db
python3 strata.py import-yaml examples/strata.strata.yaml --project strata --db /tmp/x.db
python3 strata.py serve --db /tmp/x.db                   # http://127.0.0.1:8740
python3 -m pytest -q
```

Trên máy chính, server chạy bằng systemd user `strata.service` cổng 8740: sửa Python thì `systemctl --user restart strata`, sửa CSS/JS thì chỉ cần tải lại trang (Ctrl+Shift+R).
