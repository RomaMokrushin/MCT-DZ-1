#!/usr/bin/env bash

set -uo pipefail
API=${API:-http://127.0.0.1:8080}
VM_DIR=${VM_DIR:-/var/lib/libvirt/images/cloudmaker}
NAME=test-vm
KEY=/tmp/cm_test_key
VIRSH="virsh -c qemu:///system"
SSH="ssh -i $KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 -o BatchMode=yes"

ok()   { echo -e "\e[32m[OK]\e[0m $*"; }
fail() { echo -e "\e[31m[FAIL]\e[0m $*"; echo "Для очистки: sudo bash ./cleanup.sh"; exit 1; }
field(){ python3 -c "import sys,json; print(json.load(sys.stdin).get('$1') or '')"; }
post() { curl -s -o /tmp/cm_resp -w '%{http_code}' -X POST "$API$1" -H 'Content-Type: application/json' -d "$2"; }

rm -f $KEY $KEY.pub && ssh-keygen -q -t ed25519 -N "" -f $KEY
PUB=$(cat $KEY.pub)

echo "== 1. HTTP API доступен"
curl -sf "$API/vms" >/dev/null && ok "GET /vms отвечает" || fail "API не отвечает на $API (запустите: sudo python3 app.py)"

echo "== 2. Создание ВМ через API с cloud-init (hostname + SSH-ключ)"
code=$(post /vms "{\"name\":\"$NAME\",\"cpu\":1,\"ram\":1024,\"hostname\":\"cm-test-host\",\"ssh_key\":\"$PUB\"}")
[ "$code" = 201 ] && ok "ВМ $NAME создана" || fail "создание: HTTP $code $(cat /tmp/cm_resp)"
$VIRSH list --all --name | grep -qx "$NAME" && ok "ВМ видна в virsh list" || fail "ВМ нет в virsh"

echo "== 3. Квоты: ВМ сверх лимита не создаётся"
code=$(post /vms '{"name":"test-big","cpu":100,"ram":1024}')
[ "$code" = 403 ] && ok "отказ 403: $(cat /tmp/cm_resp)" || fail "квота не сработала: HTTP $code"
$VIRSH list --all --name | grep -qx test-big && fail "test-big всё-таки создана"

echo "== 4. cloud-init применился (ждём загрузку ВМ, до ~5 мин)"
IP=""
for i in $(seq 60); do IP=$(curl -s "$API/vms/$NAME" | field ip); [ -n "$IP" ] && break; sleep 5; done
[ -n "$IP" ] && ok "IP ВМ: $IP" || fail "ВМ не получила IP"
HOST=""
for i in $(seq 40); do HOST=$($SSH user@"$IP" hostname 2>/dev/null) && break; sleep 5; done
[ "$HOST" = cm-test-host ] && ok "SSH по ключу работает, hostname=$HOST" || fail "SSH/hostname не совпал: '$HOST'"

echo "== 5. Остановка ВМ"
curl -sf -X POST "$API/vms/$NAME/stop" >/dev/null
st=$(curl -s "$API/vms/$NAME" | field state)
[ "$st" = "shut off" ] && ok "state=$st" || fail "state=$st"

echo "== 6. Запуск ВМ"
curl -sf -X POST "$API/vms/$NAME/start" >/dev/null
st=$(curl -s "$API/vms/$NAME" | field state)
[ "$st" = "running" ] && ok "state=$st" || fail "state=$st"

echo "== 7. Удаление ВМ"
curl -sf -X DELETE "$API/vms/$NAME" >/dev/null
! $VIRSH list --all --name | grep -qx "$NAME" && ok "ВМ удалена из libvirt" || fail "ВМ осталась"
[ ! -e "$VM_DIR/$NAME.qcow2" ] && ok "диск удалён" || fail "диск остался"

rm -f $KEY $KEY.pub /tmp/cm_resp
echo -e "\e[32mВсе проверки пройдены\e[0m"
