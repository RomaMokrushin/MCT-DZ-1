#!/usr/bin/env bash

VIRSH="virsh -c qemu:///system"
VM_DIR=${VM_DIR:-/var/lib/libvirt/images/cloudmaker}

for vm in $($VIRSH list --all --name | grep '^test-'); do
  $VIRSH destroy "$vm" >/dev/null 2>&1
  $VIRSH undefine "$vm" >/dev/null && echo "удалена ВМ $vm"
done
rm -fv "$VM_DIR"/test-* /tmp/cm_test_key /tmp/cm_test_key.pub /tmp/cm_resp
echo "Очистка завершена"
