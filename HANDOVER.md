# Bàn giao Strata (18/10/2026)

## Strata là gì

Công cụ cục bộ, đọc dữ liệu từ SQLite, quản lý nhiều project: task, issue, decision, trang thảo luận, mục lục tài liệu kỹ thuật, bản đồ C4, nhật ký audit. Giao diện web chỉ đọc. Mọi thao tác ghi đi qua CLI.

- Code: `/home/abel/project/tools/strata` (Python stdlib + PyYAML, JS thuần, không build, không CDN). **Chưa có git.**
- DB thật: `/home/abel/.secondbrain/strata.db`, mới có schema, chưa có dữ liệu.
- DB mẫu: `/tmp/claude-1000/-home-abel-project-tools-strata/31fe5838-bdb3-476e-9ab9-d00ef4a47539/scratchpad/demo.db`. Nằm trong `/tmp`, khởi động lại máy là mất. Tạo lại theo mục "Dựng lại DB mẫu".

## Chạy

```
python3 strata.py serve --db <đường dẫn db>      # http://127.0.0.1:8740
python3 -m venv /tmp/claude-1000/v && /tmp/claude-1000/v/bin/pip install pytest pyyaml
/tmp/claude-1000/v/bin/python -m pytest -q        # hiện tại: 93 passed
```

Lúc bàn giao, server đang chạy nền trên DB mẫu. Tắt bằng cách kill PID đang giữ cổng 8740 (`ss -ltnp 'sport = :8740'`). Sau khi sửa CSS/JS, bấm Ctrl+Shift+R trong trình duyệt. Sửa Python thì phải khởi động lại server.

## Lệnh CLI chính

`init`, `import-yaml FILE --project P`, `validate --project P`, `project add/list`, `doc scan/set`, `item add/set`, `page put/validate/list`. Xem thêm `README.md`.

## Đã xong và đã kiểm

| Phần | File | Test |
|---|---|---|
| Schema: item, decision (append-only bằng trigger), page, c4_*, c4_meta, project, doc, audit, FTS5 tiếng Việt (đ→d, truy vấn qua `db.fold`) | `strata/schema.sql`, `strata/db.py` | `tests/test_schema.py`, `test_page.py` |
| Nhập C4 từ YAML, validate trên DB | `strata/c4.py` | `test_c4.py` |
| 8 loại block cho page | `strata/blocks.py` | `test_blocks.py` |
| Server chỉ GET; chặn header Host; chặn traversal ở `/code/`, `/docs/`, `/vendor/`, `/assets/`; ẩn dotfile và file .db | `strata/server.py` | `test_serve.py`, `test_app.py`, `test_pages_web.py` |
| Khung giao diện: sidebar, Ctrl+K, các tab, phím tắt, theme tối/sáng, ánh kim quét tuần tự | `viewer/app.html`, `app.js`, `app.css`, `page.css`, `page.js` | Agent kiểm bằng ảnh chụp màn hình. Chưa ai kiểm thao tác thủ công đầy đủ |
| Viewer C4 | `viewer/index.html` (route `/c4`) | |

## Chưa xong: ảnh nền phần đầu trang Tổng quan

**Yêu cầu của user:** giống y hệt mockup `/tmp/claude-1000/-home-abel-project-tools-strata/31fe5838-bdb3-476e-9ab9-d00ef4a47539/images/5.png` (dãy núi nét vàng kim, sóng dài chạy ngang, sao nhỏ), ở dạng vector.

**Kết quả hiện tại: chưa đạt, user không chấp nhận.**

- File đang dùng: `viewer/assets/hero-mountains.svg` (núi, thân đặc, sao) và `viewer/assets/hero-mountains-waves.svg` (sóng). JS chèn thẳng SVG vào trang, màu lấy từ token theme.
- Cách đã làm: script `scripts/trace_hero.py` nhận ảnh PNG mockup, dò đường tâm các nét (skeletonize) rồi xuất SVG. Sóng thì đo tay, lưu ở `scripts/hero_waves.json`. Script cần một venv Python 3.12 tạm ở `/tmp/claude-1000/vt` (pillow, numpy, scikit-image, skan).
- Đã thử và hỏng: trace viền bằng vtracer (nét dày, vụn), núi sinh bằng code, trace đường tâm. Nét gạch trong núi ra thành vòng đồng mức, không giống nét chảy dọc sườn của mockup.
- Lúc agent bị dừng, nó đang giữa một vòng chỉnh. `trace_hero.py` có thể đang dở dang. Hai file SVG trong `viewer/assets/` là bản chạy được gần nhất. Test vẫn đạt.
- Gợi ý cho người làm tiếp: cân nhắc vẽ lại tay bằng công cụ vector (Inkscape, Figma) theo mockup, thay vì trace tự động.

## Việc còn mở khác

- Chưa có git. Nên `git init` và commit trước khi sửa tiếp.
- Chưa chạy reviewer cho đợt giao diện (từ lúc thêm khung nhiều project trở đi).
- Theo kế hoạch đã duyệt, chưa làm: T4 (lớp service có kiểm quyền theo vai và audit), T5 (nhận task nguyên tử), T6 (decision qua service), T7 (tìm kiếm), T8 (`context(role, task)`), T9 (MCP server), T10–T11 (export ra git, `CORE_RULES.md`), T12 (nhập dữ liệu từ vault), T13.
- Tài liệu kỹ thuật của project1_app chưa gán tính năng, nên mục lục đang dồn hết vào "Chưa phân nhóm" (`doc set --feature`).
- Tài liệu HTML được phục vụ cùng nguồn với app, không bị cô lập.

## Dựng lại DB mẫu

```
export STRATA_DB=/đường/dẫn/demo.db
python3 strata.py init
python3 strata.py project add internproj --name "Intern Projects"
python3 strata.py project add project1_app --name "Project 1 App" --parent internproj \
  --root /home/abel/project/internproj/project1_app --docs-dir documentation
python3 strata.py project add strata --name Strata --root /home/abel/project/tools/strata
python3 strata.py import-yaml examples/project1_app.strata.yaml --project project1_app
python3 strata.py page put examples/strata-design.page.json
python3 strata.py doc scan --project project1_app
```
