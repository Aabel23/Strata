# Endo

> **Endoskeleton framework for Hierarchical Multi-Agent Systems & Tree-sitter Repo Map Engine.**

Endo là nền tảng khung xương (backbone framework) kết hợp giữa:
1. **Tree-sitter Repo Map Engine**: Động cơ bóc tách AST, tính PageRank trọng số ký hiệu để tạo Repo Map đa tầng (Macro Map cho Orchestrator, Local Map cho Area Lead) nhằm tối ưu triệt để token context.
2. **Hierarchical Multi-Agent Architecture**: Hệ thống agent phân tầng kim tự tháp (Orchestrator $\rightarrow$ Area Lead $\rightarrow$ Coder $\rightarrow$ Verifier) giúp cô lập phạm vi tác vụ (Strict Context Scoping), loại bỏ xung đột ghi file và ảo giác khi làm việc với codebase lớn.

---

## Quản trị agent

Luật, quy trình, vai agent và hook dùng chung được quản lý tại [`../agent/`](../agent/). Agent bắt đầu từ [`../agent/BOOTSTRAP.md`](../agent/BOOTSTRAP.md) và tuân theo [`../agent/HIEN_PHAP.md`](../agent/HIEN_PHAP.md).

Strata là công cụ quản lý task, issue, tài liệu và C4; hướng dẫn agent sử dụng công cụ nằm tại [`../agent/skills/strata/SKILL.md`](../agent/skills/strata/SKILL.md).

## 🏛️ Kiến trúc C4 (Strata)

Hệ thống được thiết kế theo mô hình DAG sạch (11 objects, 12 links) tại [`docs/c4/map.yaml`](docs/c4/map.yaml):

```text
User (Chat)
  │ WS prompt
  ▼
chat (Chat Interface / Gateway)
  │ IPC task
  ▼
orchestrator (Root Orchestrator - Nắm C4 & Macro Repo Map)
  │
  ├──> repo_engine (Tree-sitter AST & Multi-tier Skeletonizer)
  │      └──> fs (Target Codebase scan)
  │
  ├──> area_lead (Subsystem Specialist - Nắm Local Map & Fault Localization)
  │      │
  │      ├──> repo_engine (Trích xuất Local Repo Map của thư mục được giao)
  │      │
  │      ├──> coder (Micro-Agent - Sửa code phẫu thuật với Mini-Context <2k tokens)
  │      │      └──> fs (Ghi file patch bị giới hạn phạm vi)
  │      │
  │      └──> verifier (Gatekeeper - Chạy test cô lập trước khi merge)
  │             └──> fs (Chạy test suite tự động)
  │
  ├──> llm (Frontier LLM - Claude, Gemini, OpenAI)
  └──> store (SQLite Task Queue, Session Memory & AST Cache)
```

Kiểm tra và import bản đồ C4 vào Strata:
```bash
python3 ../strata/strata.py c4 validate docs/c4
python3 ../strata/strata.py c4 import docs/c4 --project endo --yes
```
