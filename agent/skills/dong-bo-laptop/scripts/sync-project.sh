#!/usr/bin/env bash
# Quản lý đồng bộ realtime một project Linux <-> laptop Windows bằng Unison.
#   sync-project.sh add <ten> <duong-dan-linux> [thu-muc-windows] [--force]
#   sync-project.sh remove <ten>
#   sync-project.sh status
# Thư mục Windows mặc định: D:/PROJECT/CODE/<ten>-linux
set -euo pipefail

LAPTOP_USER=NGOCTRAN
LAPTOP_IP=$(grep -h '^root = ssh://' ~/.unison/internproj.prf | sed -E 's#.*@([^/]+)/.*#\1#')
UNISON_DIR=~/.unison
SSH="ssh -o BatchMode=yes -o ConnectTimeout=10 $LAPTOP_USER@$LAPTOP_IP"

die() { echo "LỖI: $*" >&2; exit 1; }

cmd_status() {
  echo "Laptop: $LAPTOP_USER@$LAPTOP_IP"
  $SSH hostname >/dev/null 2>&1 && echo "SSH laptop: OK" || echo "SSH laptop: KHÔNG KẾT NỐI ĐƯỢC"
  for prf in "$UNISON_DIR"/*.prf; do
    name=$(basename "$prf" .prf)
    [ "$name" = common ] || [ "$name" = default ] && continue
    state=$(systemctl --user is-active "unison-watch@$name" 2>/dev/null || true)
    roots=$(grep '^root' "$prf" | sed 's/^root = //' | paste -sd' ' | sed 's/ / <-> /')
    printf '%-14s %-9s %s\n' "$name" "$state" "$roots"
  done
}

cmd_add() {
  local name=${1:?thiếu tên} src=${2:?thiếu đường dẫn Linux} win=${3:-} force=no
  [ "$win" = --force ] && { win=; force=yes; }
  [ "${4:-}" = --force ] && force=yes
  win=${win:-D:/PROJECT/CODE/$name-linux}
  win=${win//\\//}
  src=$(realpath "$src")
  local prf="$UNISON_DIR/$name.prf"

  [[ $name =~ ^[A-Za-z0-9_-]+$ ]] || die "tên chỉ gồm chữ, số, - và _"
  [ -d "$src" ] || die "không có thư mục $src"
  [ -e "$prf" ] && die "profile $name đã có ($prf)"
  grep -l "^root = $src\$" "$UNISON_DIR"/*.prf 2>/dev/null && die "thư mục này đã được đồng bộ bởi profile trên"

  local count
  count=$($SSH "if (Test-Path '$win') { (Get-ChildItem -Force '$win' | Measure-Object).Count } else { -1 }" | tr -d '\r')
  if [ "$count" -gt 0 ] && [ "$force" = no ]; then
    die "$win trên laptop đã có $count mục. Kiểm với user trước (Linux sẽ thắng khi xung đột), rồi chạy lại với --force."
  fi
  [ "$count" -lt 0 ] && $SSH "New-Item -ItemType Directory -Force '$win' | Out-Null"

  cat > "$prf" <<EOF
include common.prf
root = $src
root = ssh://$LAPTOP_USER@$LAPTOP_IP/$win
prefer = $src
ignore = Name build
ignore = Name .gradle
EOF
  systemctl --user enable --now "unison-watch@$name"
  echo "Đã bật unison-watch@$name. Chờ lượt đồng bộ đầu..."
  for _ in $(seq 1 60); do
    if journalctl --user -u "unison-watch@$name" --since "-5min" --no-pager | grep -qE 'Synchronization complete|Nothing to do'; then
      journalctl --user -u "unison-watch@$name" --since "-5min" --no-pager | grep -E 'Synchronization complete|Nothing to do|failed|Error' | tail -3
      return 0
    fi
    sleep 2
  done
  echo "Chưa thấy lượt đầu xong sau 2 phút. Xem: journalctl --user -u unison-watch@$name -n 50"
}

cmd_remove() {
  local name=${1:?thiếu tên}
  case $name in common|default) die "không gỡ profile $name";; esac
  [ -e "$UNISON_DIR/$name.prf" ] || die "không có profile $name"
  systemctl --user disable --now "unison-watch@$name"
  mv "$UNISON_DIR/$name.prf" "$UNISON_DIR/$name.prf.removed-$(date +%Y%m%d)"
  echo "Đã tắt đồng bộ $name. File hai bên giữ nguyên."
}

case ${1:-} in
  add)    shift; cmd_add "$@" ;;
  remove) shift; cmd_remove "$@" ;;
  status) cmd_status ;;
  *) sed -n '2,6p' "$0"; exit 1 ;;
esac
