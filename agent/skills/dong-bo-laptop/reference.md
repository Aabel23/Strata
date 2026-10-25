---
id: laptop-ssh-debug-bluetooth
type: reference
scope: global
status: confirmed
source: current-conversation, user chốt 2026-10-16
valid_from: 2026-10-16
updated: 2026-10-16
supersedes: ""
---

# Laptop Windows của user: SSH vào để debug Bluetooth/thiết bị

**User chốt 16/10/2026:** sau này cần debug thứ gì phải có phần cứng mà máy Linux `abel-01` không làm tiện (Bluetooth/BLE, điện thoại Android qua ADB, Flutter chạy trên thiết bị…), agent **tự SSH vào laptop** để thao tác, không cần hỏi lại cách kết nối.

## Kết nối

```sh
ssh -o BatchMode=yes -o ConnectTimeout=10 NGOCTRAN@100.89.128.59 '<lệnh PowerShell>'
```

- Qua **Tailscale**: laptop tên `abea` (17/10/2026 đổi lại từ `abea-2`; node cũ `100.79.21.30` đã bỏ; IP đổi khi Tailscale trên laptop đăng nhập lại), IP `100.89.128.59` (máy Linux này là `abel-01`, `100.107.55.40`). Kiểm laptop có online không: `tailscale status`, `tailscale ping -c 2 100.89.128.59`.
- Đăng nhập bằng khóa `~/.ssh/id_ed25519` của `abel-01`, không có mật khẩu. User Windows là `abea\ngoctran`.
- Lệnh `ssh` cần chạy ngoài sandbox (`dangerouslyDisableSandbox`), vì sandbox chặn kết nối tới đó. Trong sandbox, lỗi hiện ra là `Connection reset by 100.89.128.59 port 22` ngay sau `SSH2_MSG_KEXINIT sent`, trông giống lỗi sshd của laptop. Gặp lỗi này thì chạy lại ngoài sandbox, đừng bảo user sửa sshd (phiên 16/10/2026).
- Khi user nói "đang cắm điện thoại", "chạy flutter", "adb"…, mặc định là thiết bị cắm vào laptop này. Đọc fact này trước rồi SSH vào, đừng kiểm `adb`/`lsusb` trên `abel-01` rồi kết luận không có thiết bị.
- Nếu timeout ở cổng 22: laptop tắt, mất Tailscale, hoặc dịch vụ `sshd` / luật firewall cổng 22 bị tắt. Báo user, không tự tìm đường khác.
- IP Tailscale của laptop có thể đổi (đã xảy ra 16/10/2026). Khi timeout, chạy `tailscale status` xem laptop có tên mới không; nếu có thì sửa `root` trong `~/.unison/internproj.prf` và `secondbrain.prf`, rồi `ssh -o StrictHostKeyChecking=accept-new` một lần với IP mới.

## Môi trường trên laptop (kiểm 16/10/2026)

- Windows 11 (NT 10.0.22631). **Shell mặc định là PowerShell**: dùng `;` để nối lệnh, không dùng `&&` hay `&`.
- **Chưa có distro WSL nào**, nên không chạy được lệnh Linux. Muốn có thì phải hỏi user trước khi cài.
- Bluetooth: `Intel(R) Wireless Bluetooth(R)`, có `Microsoft Bluetooth LE Enumerator` (đủ BLE). Đã pair sẵn `Galaxy A25 5G` và các tai nghe/loa.
- Công cụ có sẵn:
  - `python`: `E:\Program Files\Python314\python.exe`, có thêm launcher `py`.
  - `adb`: `D:\Users\NGOCTRAN\AppData\Local\Android\Sdk\platform-tools\adb.exe`.
  - `flutter`: `E:\Development\flutter-sdk\bin\flutter.bat`.
  - `git`: `E:\Program Files\Git\cmd\git.exe`.

## Đồng bộ tự động Linux ↔ laptop (Unison, user chốt 16/10/2026)

- Unison 2.54.0 (GPL-3.0). Trên Linux ở `~/.local/bin/unison`; trên laptop ở `E:\Development\unison\bin` (đã thêm vào PATH của user).
- Hai profile trong `~/.unison/`, dùng chung `common.prf`:
  - `internproj`: `/home/abel/project/internproj` ↔ `D:\PROJECT\CODE\internproj-linux`
  - `secondbrain`: `/home/abel/.secondbrain` ↔ `D:\PROJECT\CODE\secondbrain-linux`
- Quy tắc:
  - **Linux thắng** khi xung đột (`prefer`).
  - Bản bị đè lưu dự phòng tối đa 5 bản: laptop ở `E:\Development\unison-backup`, Linux ở `~/.unison/backup`.
  - Trạng thái Unison của laptop ở `E:\Development\unison-state`, vì ổ C: laptop đầy.
- Không đồng bộ: `.git`, `build`, `.gradle`, `.dart_tool`, `__pycache__`, `.venv`/`venv`, `node_modules`, `.pytest_cache`, `*.pyc`, `.env`/`*.env`, `*.pem`, `*.key`, và `.obsidian/workspace*` của vault.
- **Git chỉ dùng trên Linux.** Laptop không có `.git`, nên commit và push luôn làm trên máy Linux.
- Chạy realtime (từ 16/10/2026): 2 service `unison-watch@internproj` và `unison-watch@secondbrain` (template `~/.config/systemd/user/unison-watch@.service`), `unison <profile> -repeat watch+300`: theo dõi file bằng `unison-fsmonitor` cả hai bên, trễ ~1 giây; quét toàn bộ mỗi 5 phút để bù; `Restart=always` sau 10 giây nếu rớt mạng. Timer cũ `unison-sync.timer` đã disable (còn file, dùng lại được).
  - Xem log: `journalctl --user -u "unison-watch@*" -n 50`
  - Tạm dừng: `systemctl --user stop unison-watch@internproj unison-watch@secondbrain`
- **Không đụng hai bản cũ trên laptop:** `D:\PROJECT\CODE\InternProj` (5,3 GB, cấu trúc khác, có thay đổi chưa commit) và `D:\PROJECT\CODE\abel-s-second-brain`. User tự gộp hoặc xóa.
- Đường dẫn remote của Unison viết `ssh://NGOCTRAN@100.89.128.59/D:/...`, chỉ một dấu `/` trước ổ đĩa. Viết `//D:` thì Windows báo lỗi.
- Lệnh `scp` thường bị đóng kết nối vì SFTP chưa bật; phải dùng `scp -O`.

## Giới hạn khi thao tác

- Công cụ Read/Edit chỉ đọc và sửa file trên `abel-01`. Trên laptop phải sửa file bằng lệnh qua ssh, hoặc chép sang bằng `scp`.
- Không chạy được chương trình tương tác. Chương trình dài thì chạy nền và đọc log.
- Mỗi lệnh là một phiên ssh riêng, không giữ thư mục đang đứng hay biến môi trường giữa các lệnh.
- Laptop là máy cá nhân của user. Chỉ làm đúng việc debug được giao; cài phần mềm, đổi cấu hình hệ thống hay xóa file thì hỏi trước.
