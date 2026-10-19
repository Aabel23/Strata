---
name: research-stage
description: Quy trình mặc định cho research stage của một khối hay chủ đề thiết kế. Gồm giải thích các phương án ở mức hệ thống, làm rõ lựa chọn của user, dọn doc cũ, tự chia nhỏ vấn đề và chạy song song các agent researcher (Sonnet, effort medium), tổng hợp kèm câu hỏi cần user quyết, rồi viết note research Markdown vào vault Obsidian (tên + frontmatter chuẩn để tra bằng Obsidian MCP). LUÔN dùng khi user đang bàn một chủ đề rồi nói "deep research" (ưu tiên hơn skill deep-research chung). Cũng dùng khi user nói "research", "nghiên cứu", "chạy agent nghiên cứu", "so sánh phương án", "viết doc research", hoặc khi một khối đã chốt sơ đồ và cần đi sâu kỹ thuật.
---

# Research stage

Research stage là giai đoạn **đang bàn**: tìm hiểu, so sánh, đề xuất, ghi câu hỏi mở. Sản phẩm là note Markdown trong vault `research/<project>/`, do chat chính ghi qua Obsidian MCP (researcher không đụng vault). Khi user xác nhận đã bàn xong một chủ đề thì mới tinh chỉnh thành doc YAML chính thức trong `<docs_dir>/architect/` của Strata. Luôn theo hiến pháp: user chốt từng bước, cấm overengineer, phát hiện vấn đề thì ghi lại chứ không tự sửa code.

## 1. Hiểu đúng câu hỏi trước khi giải thích

- User nhắc tới thứ đã bàn trước ("phương án 3", "R5"…) mà không có trong ngữ cảnh hiện tại: tìm trong RAM.md, OPEN.md và trong repo. Không tìm ra thì **hỏi lại, không đoán**. Bài học: từng đoán sai "phương án 3" làm user phải sửa hai lần.
- Giải thích ở mức hệ thống trước: khối nào, ai thấy gì, dữ liệu đi đâu. Dùng ví dụ đời thường (hộp khóa, đường ống) và một bảng so sánh ngắn. Thuật toán và lý thuyết để sau, khi user hỏi.
- Tách rõ ba việc hay bị gộp chung là "mã hóa": **mã hóa** (giấu, mở lại được), **băm** (một chiều), **ký/MAC** (chứng minh nguồn gốc, nội dung vẫn rõ).
- Một lựa chọn của user khớp được với hai phương án (ví dụ "hai chặng" vừa là phương án 2 vừa là R5): hỏi một câu (a)/(b), kèm khuyến nghị.

## 2. Ghi quyết định, dọn doc cũ

- Khi user chốt: nhắc lại quyết định trong một câu.
- Dọn doc phương án cũ khi user yêu cầu:
  1. Xem tiêu đề từng file.
  2. Kiểm có file nào khác trỏ tới nó không (`grep -rl`).
  3. Kiểm file có nằm trong git không (`git ls-files`).
  4. Chép bản dự phòng vào scratchpad rồi mới xóa.
  5. File nào không chắc thuộc bộ cần dọn thì để nguyên và báo user.

## 3. "Deep research": tự chia nhỏ rồi cử agent

Khi user đang bàn một chủ đề và nói **"deep research"**: không hỏi lại cách chia, tự làm.

1. **Tự chia nhỏ vấn đề** từ những gì đã bàn:
   - mỗi khối hoặc chặng là một phần;
   - cộng một phần **xuyên suốt** (luồng nối các khối, vận hành, quản lý khóa, giảm thiệt hại).
   
   Mỗi phần phải đủ hẹp để một agent đi sâu kỹ thuật, và không trùng với phần khác.
2. **Báo user trong một dòng cho mỗi agent** (ai lo gì, case study nào), rồi chạy ngay trong cùng lượt. Không chờ user duyệt cách chia.
3. **Số agent** bằng số phần, mặc định 3, giữ dưới 5 trừ khi user muốn nhiều hơn.

Cấu hình agent:
- Chạy nền, `model: sonnet`, `effort: medium`, `subagent_type: general-purpose` (user chốt 11/10/2026: researcher dùng Sonnet medium).
- Researcher bắt buộc dùng Firecrawl MCP (`mcp__firecrawl__*`) để search/scrape web, WebSearch/WebFetch chỉ là fallback (user chốt 16/10/2026). Trước khi cử agent, kiểm `claude mcp list` thấy `firecrawl` Connected; nếu không, báo user đăng nhập lại (`claude mcp login firecrawl` hoặc `/mcp`).
- **Cấm** đưa nội dung, kết luận hay đường dẫn vault vào prompt. Chỉ đưa:
  - bối cảnh hệ thống ở mức khối;
  - các quyết định user vừa nói trong chat;
  - phạm vi code (đường dẫn repo).
  
  Thiết kế cũ hoặc tự chế thì ghi rõ "chỉ để tham chiếu và phản biện, không lấy làm nền".
- Khung prompt: xem [references/researcher-prompt.md](references/researcher-prompt.md).
- Mỗi agent xong: báo user 3–5 ý chính. **Tự kiểm trong code** mọi phát hiện nghiêm trọng trước khi nói lại với user (ví dụ lỗi bỏ qua kiểm quyền ở `guard.py`).

## 3b. Mổ xẻ tính năng có sẵn (REA)

**Không tự chạy.** Researcher chỉ *gợi ý*: trong bản tổng hợp (bước 4), thêm mục "Tính năng có thể mổ xẻ" liệt kê từng tính năng cụ thể đã có ở ứng dụng/repo khác, kèm nguồn, loại nguồn (bản phát hành hay repo mã mở) và vì sao đáng học. Chỉ khi user gọi (ví dụ "mổ xẻ tính năng X", "chạy REA cho X") mới cử agent cho đúng các tính năng user chọn (user chốt 18/10/2026).

- Cấu hình agent: chạy nền, `model: opus`, `effort: low`, `subagent_type: general-purpose`.
- **Chọn cách mổ xẻ theo loại nguồn:**
  - Nguồn là bản phát hành: app, file nhị phân, firmware, Electron, gói cài đặt, hoặc trang web chạy thật. Agent dùng skill `reverse-engineer-anything` (Hopper).
  - Nguồn là repo mã mở. Agent đọc thẳng mã nguồn, không dùng REA, vì REA không dành cho việc phân tích kiến trúc từ repo mã nguồn.
- Agent phải trả về:
  - tính năng hoạt động thế nào: khối, luồng, input/output, trạng thái;
  - **bản viết lại theo hệ thống của ta**: gắn vào khối nào, theo hợp đồng nào, giữ, bỏ hay đổi gì;
  - rủi ro khi áp dụng.
- Chỉ học cơ chế rồi tự viết lại. Không chép mã hay tài sản có bản quyền, và ghi giấy phép của nguồn.
- Quy tắc về vault giống researcher: không đưa nội dung vault vào prompt.
- Kết quả được gộp vào bước 4 và note research. Mỗi tính năng thành một mục `##` trong note, ghi rõ "đề xuất".

## 4. Tổng hợp

Đủ kết quả thì viết một bản tổng hợp gồm:

1. **Kết luận chung** các agent đồng thuận, kèm case study chứng minh.
2. **Luồng đề xuất** dạng các bước đánh số.
3. **Giữ / bỏ / thêm** so với code hiện có.
4. **Lỗi phát hiện**: dẫn file:dòng, ghi "chưa sửa, chờ user".
5. **Tính năng có thể mổ xẻ** (xem 3b): chỉ liệt kê, chờ user gọi.
6. **Câu hỏi cần user quyết**: có khuyến nghị, xếp câu nào quyết định hình dạng các phần sau lên trước.
7. **Để sau MVP.**

Agent đồng thuận với nhau không thay cho user chốt.

## 5. Viết note research (Markdown trong vault)

Chỉ chat chính ghi, qua `mcp__obsidian__write_note` (đường dẫn tương đối vault). Không ghi bằng shell, không ghi vào Strata.

1. **Đối chiếu quyết định đã chốt** (RAM.md, chat, C4 của project) để note không đi ngược. Note phải **tự đứng được**: không nhắc nhãn nội bộ ("phương án 3", "agent research"). Giải thích bằng lý do kỹ thuật và chuẩn công khai; dẫn đường dẫn code được.
2. **Trước khi tạo, tra trùng:** `search_notes` theo chủ đề và `list_directory research/<project>`. Đã có note cùng chủ đề thì cập nhật (`patch_note`, đổi `updated`), không tạo bản mới.
3. **Tên và vị trí:** `research/<project>/<chu-de>.md`
   - `<project>`: đúng tên project trong Strata (`strata.py project list`).
   - `<chu-de>`: tiếng Anh, chữ thường, nối `-`, danh từ cụ thể, không ngày tháng (vd `token-refresh-flow`, `firmware-ota-signing`). Ngày nằm ở frontmatter.
4. **Frontmatter bắt buộc** (để lọc bằng `get_frontmatter`, `search_notes`, tag):
   ```yaml
   ---
   title: "Ký firmware khi cập nhật OTA"      # tiếng Việt, đọc là hiểu
   summary: "So sánh 3 cách ký, đề xuất Ed25519 + kiểm ở bootloader"  # 1 câu, chứa từ khóa tra cứu
   project: project1_app
   topic: firmware-ota-signing               # = tên file
   status: dang-ban                          # dang-ban | da-chot | bo
   created: 2026-10-19
   updated: 2026-10-19
   keywords: [ota, ed25519, bootloader, ký số]  # từ đồng nghĩa Việt/Anh user hay gõ
   code: [src/ota/verify.c]                  # file code liên quan
   related: ["[[research/project1_app/key-management]]"]
   strata_doc:                               # điền khi đã chốt thành doc architect/
   tags: [research, project/project1_app, status/dang-ban]
   ---
   ```
   Đổi `status` thì đổi cả tag `status/…` (`manage_tags`).
5. **Bố cục thân note:**
   - Dòng đầu: `> ` tóm tắt 2–3 câu (kết luận + điều đang chờ quyết).
   - `## Bức tranh toàn cục`: khối, ai thấy gì, dữ liệu đi đâu (mermaid nếu cần).
   - `## Luồng chính`: một ví dụ thật đi hết hệ thống (các bước đánh số hoặc mermaid sequence) + bảng "Trong sơ đồ → mã nguồn hiện có → vai trò".
   - `## Thành phần: <tên>`: mỗi thành phần một mục, gồm làm gì, các bước và vì sao, trạng thái **đã chốt** / **đề xuất**.
   - `## Thuật toán và nguyên lý` (nếu là đề tài kỹ thuật).
   - `## Tính năng có thể mổ xẻ` (xem 3b).
   - `## Câu hỏi cần quyết`: mỗi câu `### Q1. …` có phương án, **Khuyến nghị**, và khi user chốt thì ghi **Đã chọn / Đã loại + lý do**.
   - `## Lỗi phát hiện`: file:dòng, "chưa sửa, chờ user".
   - `## Để sau MVP`, `## Nguồn` (link case study), `## Thuật ngữ` (bảng Thuật ngữ | Nghĩa).
6. **Kiểm:** `get_frontmatter` đọc lại đủ trường; `search_notes` bằng một keyword trong `keywords` phải ra note.

Khi user chốt chủ đề: viết doc YAML trong `<docs_dir>/architect/` theo `/home/abel/project/tools/strata/docs/architect/doc-format.yaml` (lệnh: skill `strata`), rồi đặt `status: da-chot`, điền `strata_doc` trong note.

## 6. Bàn giao

- Mở đầu bằng dòng "Viết cho: …".
- Đường dẫn note trong vault + `title`/`keywords` đã đặt. Tóm cấu trúc note trong vài gạch đầu dòng.
- Liệt kê riêng **những gì agent tự thêm, user cần duyệt**.
- Liệt kê **những gì ghi trong note nhưng chưa xử lý**: lỗi, phạm vi chưa phủ.
- Các quyết định phiên khác (ngoài note) vẫn chạy `session-secondbrain` khi user muốn.
