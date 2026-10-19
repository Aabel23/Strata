# Khởi động

File này được nạp tự động cho **mọi phiên** qua symlink `~/.claude/CLAUDE.md` và `~/.codex/AGENTS.md`.
Nguồn gốc: `/home/abel/project/tools/strata/agent/` (git). Luật, quy trình, skill, hook của agent đều sống ở đây. Sửa luật thì sửa ở đây, không sửa bản copy nơi khác.

## Agent chính (phiên chat với user)

Trước khi làm, đọc và **tuân thủ nghiêm ngặt**:

1. `/home/abel/project/tools/strata/agent/HIEN_PHAP.md`: luật và luồng làm việc. Không bỏ bước, không tự rút gọn quy trình.
2. Vault `/home/abel/.secondbrain` (chỉ qua Obsidian MCP `mcp__obsidian__*`, đường dẫn tương đối): `RAM.md` (việc đang làm), `OPEN.md` (vấn đề chưa giải quyết).

Nếu Obsidian MCP không chạy, báo user rồi làm tiếp dựa trên code.

**Trước lệnh đầu tiên chạm Strata** (ghi/đọc task, issue, doc, C4) phải nạp skill `strata`. Không đoán lệnh, không sửa DB bằng sqlite3.

Đang làm trong một project có `CLAUDE.md` riêng thì đọc thêm file đó; luật project bổ sung, không thay HIEN_PHAP.

## Subagent (được giao việc qua Agent tool)

**Không đọc vault, không đọc file này để tự mở rộng phạm vi.** Chỉ làm theo prompt được giao và phạm vi code trong prompt. Hook `agent/hooks/block_secondbrain_creative_agents.py` chặn subagent truy cập vault (best-effort; kiểm soát thật là allowlist tools trong `agent/agents/`).

## Bản đồ thư mục `agent/`

| Đường dẫn | Là gì |
|---|---|
| `HIEN_PHAP.md` | Luật lõi + luồng 6 bước |
| `agents/` | Định nghĩa vai subagent (researcher, coder, reviewer): model + allowlist tools. Symlink vào `~/.claude/agents/` |
| `skills/schematic/` | Skill ngoài, clone riêng, không nằm trong git của repo (đã `.gitignore`) |
| `skills/` | Skill tự viết/tự giữ. Symlink từ `~/.claude/skills/<tên>` (và `~/.codex/skills/session-secondbrain`) |
| `skills/strata/` | Sổ tay dùng app Strata cho agent |
| `hooks/` | Hook của Claude Code. Symlink từ `~/.claude/hooks/`, khai báo trong `~/.claude/settings.json` |

Skill từ pack ngoài (`ponytail`, `security-audit`) vẫn ở `~/.claude/packs/`, không chép vào đây.

## Thêm skill/luật mới

- Skill mới: tạo `agent/skills/<tên>/SKILL.md`, rồi `ln -s` vào `~/.claude/skills/<tên>`.
- Luật mới: sửa `HIEN_PHAP.md`. Commit sau mỗi lần đổi luật.

## Cài đặt (user làm)

Agent không tự chạy các bước này (đụng `~/.claude`, `~/.codex`).

```bash
mkdir -p ~/.claude/agents && ln -s /home/abel/project/tools/strata/agent/agents/*.md ~/.claude/agents/
claude mcp add --scope user strata -- python3 /home/abel/project/tools/strata/strata.py mcp --role main
codex mcp add strata -- python3 /home/abel/project/tools/strata/strata.py mcp --role main
```

Duyệt `.mcp.json` của project một lần trong phiên Claude Code tương tác (server `strata-coder`, `strata-reviewer`).
