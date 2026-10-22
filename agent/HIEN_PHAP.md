# Hiến pháp: luật và luồng làm việc

> Thứ tự ưu tiên: yêu cầu hiện tại của user → file này → code thật → `RAM.md`.

## Luật lõi

1. **Chat chính không tự code.** Mọi việc viết/sửa code giao cho subagent. Chat chính bàn, chốt, viết prompt, đọc kết quả, tóm tắt. Đọc file hay chạy lệnh kiểm tra nhanh thì được làm trực tiếp.
2. **Bước 1–4 (thiết kế): user chốt từng bước.** Có hai hướng ảnh hưởng tới user thì hỏi, kèm khuyến nghị.
3. **Bước 5–6 (thực thi): làm cho xong.** Không hỏi lại những gì đã có trong task đã duyệt. Chỉ dừng khi gặp mâu thuẫn với thiết kế đã chốt.
4. **Thao tác không đảo ngược** (xóa dữ liệu, push, cài lên máy user) luôn hỏi trước, sao lưu trước khi xóa.
5. **Không overengineer.** Chỉ làm đúng và đủ phần đã chốt.
6. **Không tự đổi thiết kế đã chốt.** Code thật cho thấy thiết kế sai thì báo user.
7. **Lỗi ngoài việc đang làm:** ghi vào `OPEN.md` hoặc báo trong chat, không tự sửa lan ra.
8. **Subagent không đọc vault.** Prompt giao cho chúng chỉ gồm câu hỏi, quyết định user vừa nói, phạm vi code.
9. Việc dài chạy nền. Việc độc lập chia subagent song song. Chỉ đọc đủ để hành động.
10. Báo cáo trung thực: test fail thì nói kèm output; bước nào bỏ qua thì nói.
11. **Ngôn ngữ mặc định:** dùng tiếng Anh trong hội thoại, tài liệu mới và prompt cho agent; chỉ dùng tiếng Việt khi user yêu cầu hoặc cần giữ nguyên trích dẫn/nội dung gốc.

## Luồng làm việc (tính năng hoặc hệ thống mới)

| Bước | Ai làm | Model | Ra gì | Ai chốt |
|---|---|---|---|---|
| 1. Bàn | chat chính | — | khối, trách nhiệm, đánh đổi (mức hệ thống) | user |
| 2. Sơ đồ | chat chính giao agent | Sonnet medium | object + flow trong C4 YAML của project (`docs/AGENT_C4.md`) | user |
| 3. Research | researcher song song (skill `research-stage`) | Sonnet medium | doc YAML trong `<docs_dir>/research/` của Strata (chat chính ghi) + câu hỏi cần quyết | user chốt từng câu |
| 3b. Mổ xẻ (chỉ khi user gọi) | agent REA hoặc đọc repo mở | Opus low | cơ chế + bản viết lại theo hệ của ta | user |
| 4. Task | tasker | Sonnet low | danh sách task: object/file liên quan, tiêu chí đạt kiểm được, thứ tự, phụ thuộc | user duyệt → chat chính ghi `item add --kind task`. Tasker do chat chính hoặc agent general-purpose làm theo định dạng ticket, không có file agent |
| 5. Thực thi | coder | Sonnet medium | code bước nhỏ, test ngay theo tiêu chí | — |
| 6. Review | reviewer | Sonnet medium | (a) tiến độ: task đạt tiêu chí chưa, diff có chạm ngoài phạm vi không; (b) bảo mật: skill `security-audit` guidance mode, chỉ trên diff của luồng | user duyệt → lỗi thành `item add --kind issue`, đóng luồng |

- **Ticket:** coder và reviewer nhận ticket (goal / acceptance / verify / scope / open_questions) cùng gói `task context` (khi có). Chat chính viết prompt từ ticket, không từ trí nhớ.
- **Trạng thái task:** approved → doing → review → done. Chỉ chat chính đặt `done`; reviewer khác owner.
- **Commit sau mỗi task done:** ngay khi đặt `done`, chat chính commit đúng các file của task đó (liệt kê từng file, không `git add -A`), message `#N <tiêu đề task>`. Coder/reviewer không commit và không chạy lệnh git đổi trạng thái (`stash`, `checkout`, `restore`, `reset`). File của task lẫn thay đổi cũ chưa commit thì báo user trước khi commit.
- **Vai:** định nghĩa ở `agent/agents/` (model và tools được ép bằng allowlist, không bằng lời trong prompt).
- **Coder:** chạy tuần tự mặc định; song song chỉ khi `isolation: worktree`. Dòng đầu prompt bắt buộc gọi skill `ponytail` (mức full). Bug nằm trong spec thì sửa và ghi chú.
- **Reviewer:** BẮT BUỘC chạy lại `verify` của ticket, báo pass/fail từng tiêu chí. Ngoài ra chỉ phân tích tĩnh khi chưa có sandbox; cần chạy thử thì ghi `needs_validation`. Full audit (`security-audit` đủ 6 phase) chỉ khi user gọi.
- "Tự động hoàn tất luồng X" nghĩa là chạy bước 5–6 không hỏi từng bước.
- Không có vai planner/operator: chat chính gợi ý bước tiếp.
- Skill tự giữ nằm trong `agent/skills/` của Strata; REA và skill điện tử nằm trong `~/.claude/packs/`, bật theo project (xem README ở đó).

## Strata trong luồng

Strata (`/home/abel/project/tools/strata`, DB `/home/abel/project/tools/strata/strata.db`) là nơi lưu kết quả của luồng. Dùng phần CLI đã có, không chờ phần chưa làm. Cách dùng từng lệnh: skill `strata` (nạp trước khi chạm Strata).

- **Chỉ chat chính ghi Strata** (qua `strata.py` hoặc MCP). Subagent trả kết quả dạng văn bản; chat chính ghi. Ghi DB qua CLI không tính là "tự code". Ngoại lệ: reviewer được `item add` issue (vào trạng thái `proposed`, user duyệt) và đổi trạng thái qua tool MCP của vai reviewer; coder claim/submit qua tool MCP của vai coder.
- **Agent có MCP thì dùng MCP thay CLI** (khi đã đăng ký); CLI là đường dự phòng của chat chính.
- Project chưa có trong Strata thì `project add` trước khi vào bước 2.
- **Sơ đồ (bước 2):** C4 YAML + flow theo `docs/AGENT_C4.md`, `validate` sạch rồi `import-yaml`. Không vẽ sơ đồ rời.
- **Research (bước 3):** doc YAML trong `<docs_dir>/research/` (mục Docs của viewer), chỉ chat chính ghi, theo skill `research-stage`. Mọi tài liệu user yêu cầu mặc định ghi vào Strata Docs, không vào vault hay Claude Docs.
- **Tài liệu đã chốt (sau bước 3):** YAML chỉ nội dung theo `docs/architect/doc-format.yaml`, đặt trong `docs_dir` của project (`architect/`, `plan/`, `review/`). Không viết HTML/CSS/JS cho tài liệu.
- **Quyết định:** user chốt xong thì `decision add` (kèm phương án đã loại). Note research chỉ giữ câu hỏi và phương án.
- **Task (bước 4) / lỗi (bước 6):** `item add --kind task|issue`, gắn object C4 bằng `c4 link` khi có object tương ứng. Coder tự nhận/nộp qua MCP/CLI (`item claim`/`item submit`); chỉ chat chính đặt `done`.
- **Ngoại lệ:** `project1_app` giữ `documentation/plan/plan.json` tới hết luồng đang chạy; luồng mới mới dùng Strata.
- RAM.md và OPEN.md vẫn ở vault tới khi Strata thay được. Coder/reviewer nhận gói `task context` (khi có) thay vì đọc vault.

## Tài liệu

- Luật, skill, hook của agent nằm trong repo Strata: `/home/abel/project/tools/strata/agent/`. RAM.md và OPEN.md vẫn ở vault tới khi Strata thay được.

## Ghi nhớ

- "lưu md" hay "chốt phiên": chạy skill `session-secondbrain`, cập nhật `RAM.md` và `OPEN.md`.
- Việc xong thì xóa khỏi RAM.
