# Hướng dẫn agent: thiết kế và sửa bản đồ C4 trong Strata

Strata giữ kiến trúc dự án trong SQLite (`/home/abel/project/tools/strata/strata.db`), nhập từ một file YAML.
Viewer vẽ map C4 zoom được (L1 hệ thống → L4 file/hàm) và tô từng bước của flow lên map.
Agent đọc map qua CLI (văn bản gọn), chỉ mở YAML ở phần cần sửa.

## 1. Đọc tối thiểu (làm theo thứ tự, dừng khi đủ)

```
export STRATA_DB=/home/abel/project/tools/strata/strata.db         # hoặc thêm --db FILE sau từng lệnh con
python3 strata.py c4 context --project P                 # cây object + interface + flow + connection
python3 strata.py c4 context --project P --object X      # một object: cha, con, connection, issue, flow
python3 strata.py c4 flow --project P                    # danh sách flow, số bước
python3 strata.py c4 flow --project P --id F             # trace từng bước, một dòng một bước
```

- `context` tự cắt theo `--max-tokens` (mặc định 2000); thiếu thì dùng `--object`.
- Chỉ `grep -n` rồi đọc đoạn YAML có id cần sửa; không đọc cả file.
- Dòng trace: `N. A → B [kind] text (interface) | payload: …`; `[call ↩]` là bước trả về; `N. @ X` là xử lý trong X.

## 2. Thứ tự thiết kế

1. **L1**: `actor`, `system` (người dùng, hệ ngoài). Mỗi cái một dòng description.
2. **L2**: `app`, `store` trong system. Ghi `technology`.
3. **L3**: `component` trong app: `responsibilities` (3–5 gạch), `state`, `interfaces` công khai.
4. **L4**: `file`/`function` chỉ cho module đáng soi (đường đi chính của flow, chỗ bảo mật). Không chép hết code.
5. **Connection** cho mọi lời gọi thật, ở tầng thấp nhất cần cho flow (L4 `call`), giữ thêm bản L2/L3 tóm tắt.
6. **Flow** cuối cùng, chỉ dùng connection/object đã có.

## 3. Quy ước YAML

- Mỗi thực thể một dòng flow-style `{...}`; chuỗi có `:` `?` `{` `}` `,` `#` thì **bắt buộc** bọc `"..."` (dấu phẩy không bọc sẽ cắt chuỗi, `validate` báo `key lạ`).
- id ngắn, snake_case, ổn định (đổi id = mất link/issue gắn với nó). Tên hiển thị để ở `name`.
- Không lặp dữ liệu: shape request/response để ở interface (`input/output`) hoặc connection (`payload`);
  `payload` của step chỉ ghi khi khác hoặc cụ thể hơn (giá trị thật của lần gọi này).
- `links` trỏ file thật, tương đối với `root`; `validate` báo link chết. Bắt buộc với app/component/file/function (thiếu → dấu "!" trên map); actor/system/store/group không bắt buộc (store nên trỏ migrations/schema).

```yaml
objects:
  - {id: server, type: app, parent: platform, name: Cloud server, technology: Python, links: [server/main.py], description: Điểm vào HTTP}
  - {id: relay, type: component, parent: server, name: relay, state: RAM-only, responsibilities: [Xếp lệnh app → máy], links: [server/src/relay/relay.py], description: Chuyển lệnh}
  - {id: r_file, type: file, parent: relay, name: relay.py, links: [server/src/relay/relay.py], description: RelayHub + handler}
  - {id: r_hub_send, type: function, parent: r_file, name: RelayHub.send, links: [server/src/relay/relay.py], description: Tạo Pending, chờ kết quả}
connections:
  - {id: rh_send, from: r_cmd_send, to: r_hub_send, name: RelayHub.send, kind: call, technology: in-process}
  - {id: fc_net, from: fc_send, to: t_do_post, name: POST phong bì, kind: network, technology: HTTPS + HPKE, payload: {request: "...", response: "..."}}
interfaces:
  - {id: hub_send, object: r_hub_send, kind: function, name: RelayHub.send, signature: "send(*, user_id, machine_id, ...) -> HandlerResult", errors: [BUSY 409]}
flows:
  - id: menu_refresh
    name: Làm mới menu
    steps:
      - {connection: u_pull, text: Kéo để làm mới}
      - {connection: rh_send, interface: hub_send}
      - {at: r_hub_send, text: tạo Pending trong RAM}
      - {connection: rh_send, reverse: true, text: trả HandlerResult}
```

## 4. Luật viết flow

- Một flow = một hành động người dùng thấy được (hoặc một sự kiện hệ thống). id dạng `menu_refresh`.
- Mỗi hop là một step: `{connection: id}`. Xử lý bên trong một object (không gửi message) là `{at: id}`.
- Phản hồi đi ngược connection đã có: `{connection: id, reverse: true}`. **Không** tạo connection ngược.
- Hàng đợi/condition giữa hai thread cũng là connection (`kind: queue`), để flow không bị đứt.
- Liên tục: điểm đầu của bước k+1 phải trùng (hoặc là cha/con của) điểm cuối bước k. `validate` cảnh báo `đứt mạch`.
- Bước gọi hàm có contract thì thêm `interface: <id>`.
- Mục tiêu 5–15 bước cho flow bình thường. Flow qua nhiều tiến trình (app → server → máy → về) có thể dài hơn;
  khi đó vẫn giữ đủ hop, cắt bớt chữ, không cắt bước.
- `text` ngắn (≤ ~12 từ), nói việc làm ở bước đó, không nhắc lại tên connection.

## 5. Vòng sửa

```
grep -n "<id>" examples/<p>.strata.yaml                     # tìm chỗ sửa
python3 strata.py validate examples/<p>.strata.yaml         # phải 0 lỗi; cố 0 cảnh báo "đứt mạch"
python3 strata.py import-yaml examples/<p>.strata.yaml --project <p>
python3 strata.py c4 flow --project <p> --id <flow>   # đọc lại trace
```

Dữ liệu đổi thì chỉ cần reload trang viewer; không cần `systemctl --user restart strata` (chỉ cần khi sửa Python).
`import-yaml` là upsert và xoá phần không còn trong YAML, nên YAML là nguồn sự thật của map.

## 6. Tham chiếu trường

| Thực thể | Trường bắt buộc | Trường tuỳ chọn |
|---|---|---|
| object | `id`, `type` (actor/system/app/store/component/group/file/function) | `name`, `parent`, `technology`, `description`, `tags`, `links`, `status` (live/future/deprecated/removed), `responsibilities`, `state` |
| connection | `id`, `from`, `to` | `name`, `kind` (network/call/queue), `technology`, `interface` (thuộc `to`), `payload {request, response}`, `direction`, `feature`, `description`, `status`, `tags` |
| interface | `id`, `object` | `kind` (http/function/queue/event), `name`, `signature`, `purpose`, `input`, `output`, `errors` |
| flow | `id`, `steps` | `name` |
| step | đúng một: `connection` \| `at` \| (cũ) `from`+`to` | `id`, `reverse` (chỉ với connection), `text`, `payload` (chuỗi), `interface` |

Cha hợp lệ: actor/system → top hoặc group; app/store → system/group; component → app/group; file → component/file; function → component/file.
Ví dụ đầy đủ: `examples/project1_app.strata.yaml` (flow `menu_refresh`, `login`, `command`).
