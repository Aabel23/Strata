# ⛰ Strata

Kiến trúc C4 viết dưới dạng code. Bạn mô tả hệ thống trong một file YAML, rồi xem nó qua một viewer có thể zoom qua các tầng.
Ý tưởng lấy từ IcePanel: **model trước, sơ đồ sau**.

Tài liệu viết bằng YAML thuần nội dung, đặt trong `docs_dir`; server tự quét và vẽ (xem `docs/architect/doc-format.yaml`). Ngoài ra: [docs/architect/ARCHITECTURE.md](docs/architect/ARCHITECTURE.md) (kiến trúc, dữ liệu, server, cách mở rộng) · [docs/AGENT_C4.md](docs/AGENT_C4.md) (agent vẽ/sửa map).

Dữ liệu nằm trong SQLite (`$STRATA_DB`, hoặc `--db FILE`). YAML chỉ là định dạng nhập.

```
python3 strata.py import-yaml examples/project1_app.strata.yaml --project project1   # nạp vào DB (upsert, xóa phần đã bỏ)
python3 strata.py validate --project project1        # kiểm tra từ DB (hoặc: validate FILE.yaml)
python3 strata.py serve --project project1           # http://127.0.0.1:8740
```

Viewer cần server (`/api/c4`), không mở trực tiếp file HTML được nữa. Link tới code lấy gốc từ `root` trong YAML, đổi thành đường dẫn tuyệt đối lúc import.
Map C4 chỉ hiện trong tab Kiến trúc của app shell (`/#/p/P/c4`); mở `/c4?project=P` trực tiếp sẽ chuyển về đó.

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

Route (POST, chỉ các ngoại lệ C4 có phạm vi hẹp — xem [CLAUDE.md](CLAUDE.md) luật cứng #1): `/api/c4/object` nhận `op=create|update|move|delete` (payload object/fields tương ứng; payload cũ `{id, fields}` vẫn sửa name/description/technology/status); `/api/c4/port` nhận `op=create|update|delete`; `/api/c4/link` nhận `op=create|update|delete`. Bố cục do viewer tự tính, không lưu. Các route giữ kiểm tra Host/Origin/JSON/size, validate model, ghi DB và audit transactionally. SQLite là nguồn chuẩn; YAML chỉ import/export.

### Liên kết object với task/decision, context cho agent

```
python3 strata.py c4 link --project P --object X --item ID        # hoặc --decision ID; unlink cùng cú pháp
python3 strata.py c4 links --project P --object X                  # liệt kê item/decision đã gắn
python3 strata.py c4 context --project P [--object X] [--max-tokens 2000]   # văn bản gọn cho agent
python3 strata.py c4 flow --project P [--id F]                              # trace từng bước của flow
```

Agent thiết kế/sửa map: đọc [docs/AGENT_C4.md](docs/AGENT_C4.md) trước.

`link/unlink` có audit (`c4.link`/`c4.unlink`); link trùng không ghi thêm. `context` không có `--object` thì in tổng quan cả map (kèm số issue mở); có `--object` thì in object, chuỗi cha, con, connection đã gộp, item/decision liên quan, flow; quá `--max-tokens` (ước len/4) thì cắt từ flow ngược lên, phần cắt ghi `... (cắt: <phần>)`.
`/api/c4` trả thêm `issues` (dead_link/no_link/no_desc theo object), `links` và `open_issues`; viewer vẽ huy hiệu "!" cho object có vấn đề, viền đỏ cho object có issue mở, và có ô tìm object.

## Hướng dẫn dùng bản đồ C4

**Chuẩn bị**
- `python3 strata.py import-yaml FILE.yaml --project P` nạp model vào DB.
- `python3 strata.py serve --project P` rồi mở tab Kiến trúc trong app shell (`/#/p/P/c4`).

**Đọc một ô**: icon, tên, nhãn loại (Người dùng / Hệ thống / Ứng dụng / Kho dữ liệu / Thành phần), technology và 1–2 dòng mô tả. Rê chuột vào ô để xem mô tả đầy đủ. Ô có chồng thẻ phía sau và dòng "N thành phần bên trong ›" ở chân là ô mở ra được. Ô nét đứt ghi "Bên ngoài tầng này". Hộp "Chú giải" ở góc phải trên canvas giải thích các ký hiệu, gập/mở được (nhớ lựa chọn).

**Các tầng và zoom vào/ra**
- Tầng 1 Context (actor, system), tầng 2 Container (app, store), tầng 3 Component. Mỗi lần chỉ vẽ con trực tiếp của object đang zoom. Thanh breadcrumb ghi rõ tầng, vd "Tầng 2 · Bên trong Cloud server".
- Bấm một ô: chọn ô, làm nổi connection của nó và các ô nối với nó, làm mờ phần còn lại, mở panel chi tiết. Bấm nền hoặc `Esc` để bỏ chọn.
- Đi vào: bấm "… bên trong ›" ở chân ô, double-click, `Enter` khi đang chọn ô, hoặc nút "Zoom vào" ở panel. Camera bay vào ô rồi tầng con nở ra từ chính vị trí ô đó.
- Đi ra: nút Up, `Esc` khi không chọn gì, hoặc breadcrumb; tầng con thu lại vào ô của nó. ← → / Back / Forward của trình duyệt cũng chạy cùng hiệu ứng. Hiệu ứng tắt khi hệ điều hành bật "giảm chuyển động".
- Đi lui/tới theo lịch sử: nút ← → cạnh breadcrumb, `Alt+←` / `Alt+→`, hoặc nút Back/Forward của trình duyệt. Mỗi lần đổi tầng là một bước lịch sử.
- Cuộn chuột để phóng/thu, kéo nền để di chuyển, nút Fit để vừa khung.

**Tìm object**: gõ vào ô "Tìm object…" ở thanh dưới (gợi ý theo id/tên), Enter hoặc chọn gợi ý. Viewer nhảy tới tầng chứa object, chọn và căn giữa nó. Không khớp thì hiện "Không tìm thấy".

**Lọc tag**: ô "Tags" ở thanh dưới; object không có tag đó bị làm mờ.

**Flow từng bước**: panel phải, tab "Diagram flows", chọn flow. Dùng « Previous / Next » hoặc bấm một step; connection của step đang chọn được tô sáng. Khi đã chọn flow, phím `←` / `→` đổi step.

**Panel chi tiết** (bấm một object):
- Code: link tới file code thật (mở tab mới); link http(s) mở nguyên văn.
- Vấn đề: lý do object có huy hiệu "!".
- Liên quan: task/issue/decision đã gắn bằng `c4 link`.
- Bấm một connection để xem mô tả, technology, status.

**Huy hiệu "!"** (góc trên phải object): object có vấn đề chất lượng model: link code chết (`dead_link`), không có link (`no_link`), thiếu mô tả (`no_desc`). Rê chuột để xem lý do. **Viền đỏ**: object có issue mở gắn vào.


Trong tab Kiến trúc: map, chú giải, tag/tìm object và panel Chi tiết/Flow; lên tầng bằng `Esc`, vào trong bằng bấm đúp.

**Phím tắt** (không có tác dụng khi đang gõ trong ô nhập hoặc select):

| Phím | Tác dụng |
|---|---|
| `Esc` | Bỏ chọn ô; nếu không chọn gì thì lên một tầng |
| `Enter` | Đi vào bên trong ô đang chọn |
| `Alt+←` / `Alt+→` | Lùi / tới trong lịch sử các tầng |
| `←` / `→` | Step trước / sau (khi đã chọn flow) |
| `f` | Vừa khung |
| `+` hoặc `=` | Phóng to |
| `-` | Thu nhỏ |
| `Ctrl+K` | Tìm toàn văn (chỉ trong app shell) |

**Cho agent** (xem thêm mục "Liên kết object với task/decision"):
- `c4 link --project P --object X --item ID` (hoặc `--decision ID`) gắn; `unlink` gỡ.
- `c4 links --project P --object X` liệt kê cái đã gắn.
- `c4 context --project P [--object X] [--max-tokens N]` in văn bản gọn để đưa vào prompt.

## Tầng C4

| type | Tầng | Được nằm trong |
|---|---|---|
| `actor`, `system` | 1 Context | top level, `group` |
| `app`, `store` | 2 Container | `system` |
| `component` | 3 Component | `app` |
| `file`, `function` | 4 Code | `component`, `file` |
| `group` | gom nhóm (domain) | top level, `group`, `system`, `app` |

Mỗi object có `links:` trỏ tới file code thật, và lệnh `validate` báo link nào đã chết.

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
  - {id, name, steps: [{id?, connection: id, reverse?: true | at: object id, text?, payload?, interface?}]}   # xem docs/AGENT_C4.md
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
