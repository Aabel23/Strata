---
name: dong-bo-laptop
description: Thêm, gỡ hoặc kiểm tra đồng bộ realtime một project giữa máy Linux abel-01 và laptop Windows của user (Unison watch qua Tailscale). Dùng khi user nói "đồng bộ project", "sync sang laptop", "thêm project vào đồng bộ", "setup project mới cho laptop", "laptop chưa thấy file", "bỏ đồng bộ", hoặc hỏi project nào đang được đồng bộ.
---

# Đồng bộ project Linux ↔ laptop

Chi tiết kết nối và lịch sử sự cố: `reference.md` (cùng thư mục skill). Đọc file đó khi có lỗi kết nối.

## Cách hệ thống chạy
- Mỗi project là một profile `~/.unison/<ten>.prf` (include `common.prf`: Linux thắng xung đột, giữ 5 bản dự phòng, bỏ `.git`/`node_modules`/`.venv`/…).
- Mỗi profile chạy một service `unison-watch@<ten>` (`unison <ten> -repeat watch+300`): trễ ~1 giây, quét lại toàn bộ mỗi 5 phút, tự kết nối lại sau 10 giây.
- Git chỉ dùng trên Linux; laptop không có `.git`.
- Lệnh `ssh` tới laptop phải chạy ngoài sandbox.

## Các bước
1. **Kiểm hiện trạng:** `scripts/sync-project.sh status`. SSH laptop hỏng thì xử lý trước (xem mục Sự cố).
2. **Chốt với user:** tên profile, thư mục Linux, thư mục Windows (mặc định `D:/PROJECT/CODE/<ten>-linux`). Nếu thư mục Windows đã có file, nói rõ Linux sẽ thắng khi xung đột và hỏi trước.
3. **Thêm:** `scripts/sync-project.sh add <ten> <duong-dan-linux> [thu-muc-windows]`.
   - Script từ chối nếu thư mục Windows không rỗng; chỉ thêm `--force` sau khi user đồng ý.
   - Project có thư mục build/lớn riêng (ví dụ `dist`, `target`, `.next`) thì thêm `ignore = Name ...` vào profile rồi `systemctl --user restart unison-watch@<ten>`.
4. **Kiểm hai chiều:** tạo file thử ở mỗi bên, xác nhận sang bên kia trong vài giây, rồi xóa.
5. **Gỡ:** `scripts/sync-project.sh remove <ten>` (chỉ tắt đồng bộ, không xóa file).
6. Báo user: profile, hai đường dẫn, kết quả lượt đầu, kết quả thử.

## Sự cố thường gặp
- **`connect to host … port 22: Connection timed out`:** IP Tailscale laptop đổi (cài lại Tailscale). `tailscale status` tìm laptop (tên `abea*`), sửa IP ở dòng `root` của mọi `~/.unison/*.prf`, `ssh -o StrictHostKeyChecking=accept-new NGOCTRAN@<ip-mới> hostname`, rồi restart các `unison-watch@*`. Cập nhật IP trong fact.
- **SSH bị từ chối/không có cổng 22:** service `sshd` trên laptop hỏng. Nếu báo "marked for deletion", user chạy script sửa bằng quyền Admin (dừng sshd, `msiexec /fa {7E239BB2-181B-42C7-8C01-F0F0FC3F6CE7}`, đặt Automatic). Không tự đổi service Windows khi chưa được phép.
- **`Connection reset` ngay sau KEXINIT:** do sandbox, chạy lại ngoài sandbox.
- Log: `journalctl --user -u "unison-watch@*" -n 50`.
