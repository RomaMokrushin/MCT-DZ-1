# Cloud Maker

Запуск виртуалок на QEMU/KVM через libvirt (virt-install / virsh) и небольшой HTTP API на Flask.

## Что сделано

- Базовое задание: ВМ запускается из консоли без GUI (4)
- 1. Приложение с HTTP API: создание / старт / остановка / удаление ВМ (2) - `app.py`
- 2. cloud-init: hostname, SSH-ключ, пароль, свой user_data (2)
- 9. Квоты на CPU и RAM (2)
- 11. Скрипт проверки `test.sh` (2)
- 12. Скрипт очистки `cleanup.sh` (1)

- 13 баллов
## Подготовка (Ubuntu)

```bash
sudo apt update
sudo apt install -y qemu-system-x86 qemu-utils libvirt-daemon-system virtinst cloud-image-utils python3-flask curl wget
sudo systemctl enable --now libvirtd
sudo virsh net-start default
sudo virsh net-autostart default
ls /dev/kvm
```

Базовый образ:

```bash
sudo mkdir -p /var/lib/libvirt/images/cloudmaker
sudo wget -O /var/lib/libvirt/images/cloudmaker/base.img https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img
```

## Как запускается ВМ


Вручную:

```bash
cd /var/lib/libvirt/images/cloudmaker
sudo qemu-img create -f qcow2 -F qcow2 -b base.img manual-vm.qcow2 10G
sudo cloud-localds manual-seed.iso <путь>/cloud-init/user-data <путь>/cloud-init/meta-data
sudo virt-install --name manual-vm --memory 1024 --vcpus 1 \
  --disk path=manual-vm.qcow2,format=qcow2 --disk path=manual-seed.iso,device=cdrom \
  --import --os-variant ubuntu22.04 --network network=default --graphics none --noautoconsole
sudo virsh list --all
sudo virsh console manual-vm
```

Удалить: `sudo virsh destroy manual-vm; sudo virsh undefine manual-vm; sudo rm /var/lib/libvirt/images/cloudmaker/manual-*`

## API

Запуск: `sudo python3 app.py` (порт 8080). Лимиты квот: `MAX_CPU` (по умолчанию 4), `MAX_RAM` в МБ (по умолчанию 4096).

- `GET /vms`, `GET /vms/<name>` - список и инфо (с IP)
- `POST /vms` - создать, JSON: name, cpu, ram, disk, hostname, ssh_key, password, user_data
- `POST /vms/<name>/start`, `POST /vms/<name>/stop`
- `DELETE /vms/<name>`
- `GET /quota`

Если суммарные CPU/RAM всех ВМ с новой превысят лимит, вернётся 403 и ВМ не создастся.

## Проверка

В одном терминале `sudo python3 app.py`, в другом:

```bash
sudo bash ./test.sh
```

Скрипт создаёт ВМ через API, проверяет квоту (ВМ сверх лимита не создаётся), заходит по SSH и смотрит
hostname, потом останавливает, запускает и удаляет ВМ. В конце должно быть "Все проверки пройдены",
все строки `[OK]`.

## Очистка

```bash
sudo bash ./cleanup.sh
```
