# Endo

> **Endoskeleton framework for AI coding agents.**

Endo là nền tảng khung xương (backbone / scaffolding framework) định hình toàn bộ hệ thống agent:
- **Code Intelligence**: Bóc tách cấu trúc AST bằng Tree-sitter, tạo Repo Map/Skeleton (rút gọn 90%+ token) thay vì nạp cả codebase.
- **Surgical Tools**: Bộ công cụ tìm kiếm và bóc tách chính xác (ripgrep, file slicer) để agent tra cứu đúng dòng code khi cần.
- **Agent Kernel**: Bộ điều phối luồng suy nghĩ, lắp ráp prompt tối ưu và thực thi tool loop.
- **State & Cache**: Lưu trữ trạng thái phiên làm việc và cache AST băm vào SQLite.

## Cấu trúc kiến trúc C4 (Strata)

Kiến trúc dự án được quản lý trực tiếp qua Strata tại `docs/c4/`:
- `map.yaml`: Định nghĩa các tầng System, App, Component và Link kết nối.

Kiểm tra và import bản đồ C4:
```bash
python3 ../strata/strata.py c4 validate docs/c4
python3 ../strata/strata.py c4 import docs/c4 --project endo --yes
```
