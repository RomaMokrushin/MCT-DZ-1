#!/usr/bin/env python3

import json
import os
import re
import subprocess
import tempfile

from flask import Flask, jsonify, request

VM_DIR = os.environ.get("VM_DIR", "/var/lib/libvirt/images/cloudmaker")
BASE_IMAGE = os.environ.get("BASE_IMAGE", os.path.join(VM_DIR, "base.img"))
OS_VARIANT = os.environ.get("OS_VARIANT", "ubuntu22.04")
MAX_CPU = int(os.environ.get("MAX_CPU", "4"))
MAX_RAM = int(os.environ.get("MAX_RAM", "4096"))
NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]{0,39}$")

app = Flask(__name__)


class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code, self.msg = code, msg


@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify(error=e.msg), e.code


@app.errorhandler(RuntimeError)
def handle_runtime_error(e):
    return jsonify(error=str(e)), 500


def run(*cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}: {(r.stderr or r.stdout).strip()}")
    return r.stdout


def virsh(*args):
    return run("virsh", "-c", "qemu:///system", *args)


def vm_names():
    return virsh("list", "--all", "--name").split()


def vm_info(name):
    info = {}
    for line in virsh("dominfo", name).splitlines():
        k, _, v = line.partition(":")
        info[k.strip()] = v.strip()
    return {
        "name": name,
        "state": info.get("State"),
        "cpu": int(info.get("CPU(s)", 0)),
        "ram_mb": int(info.get("Max memory", "0").split()[0]) // 1024,
    }


def vm_ip(name):
    try:
        out = virsh("domifaddr", name)
    except RuntimeError:
        return None
    m = re.search(r"(\d+\.\d+\.\d+\.\d+)/", out)
    return m.group(1) if m else None


def require_vm(name):
    if name not in vm_names():
        raise ApiError(404, f"ВМ {name} не найдена")


def make_user_data(hostname, ssh_key, password):
    user = {"name": "user", "sudo": "ALL=(ALL) NOPASSWD:ALL",
            "shell": "/bin/bash", "groups": "sudo"}
    if ssh_key:
        user["ssh_authorized_keys"] = [ssh_key]
    if password:
        user["lock_passwd"] = False
        user["plain_text_passwd"] = password
    cfg = {"hostname": hostname, "users": [user], "ssh_pwauth": bool(password)}
    return "#cloud-config\n" + json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"


@app.get("/vms")
def list_vms():
    return jsonify([vm_info(n) for n in vm_names()])


@app.get("/vms/<name>")
def get_vm(name):
    require_vm(name)
    return jsonify({**vm_info(name), "ip": vm_ip(name)})


@app.get("/quota")
def quota():
    vms = [vm_info(n) for n in vm_names()]
    return jsonify(cpu_used=sum(v["cpu"] for v in vms), cpu_max=MAX_CPU,
                   ram_used_mb=sum(v["ram_mb"] for v in vms), ram_max_mb=MAX_RAM)


@app.post("/vms")
def create_vm():
    d = request.get_json(force=True, silent=True) or {}
    name = str(d.get("name", ""))
    hostname = str(d.get("hostname") or name)
    if not NAME_RE.match(name) or not NAME_RE.match(hostname):
        raise ApiError(400, "name/hostname: латиница, цифры и '-', до 40 символов")
    try:
        cpu, ram, disk_gb = int(d.get("cpu", 1)), int(d.get("ram", 1024)), int(d.get("disk", 10))
    except (TypeError, ValueError):
        raise ApiError(400, "cpu, ram, disk должны быть числами")
    if cpu < 1 or ram < 256 or disk_gb < 3:
        raise ApiError(400, "минимум: cpu=1, ram=256, disk=3")
    if not os.path.exists(BASE_IMAGE):
        raise ApiError(500, f"нет базового образа {BASE_IMAGE}")

    # Квоты: суммарные ресурсы всех ВМ на хосте + новая ВМ
    vms = [vm_info(n) for n in vm_names()]
    if any(v["name"] == name for v in vms):
        raise ApiError(409, f"ВМ {name} уже существует")
    used_cpu = sum(v["cpu"] for v in vms)
    used_ram = sum(v["ram_mb"] for v in vms)
    if used_cpu + cpu > MAX_CPU or used_ram + ram > MAX_RAM:
        raise ApiError(403, f"квота превышена: CPU {used_cpu}+{cpu} > {MAX_CPU} "
                            f"или RAM {used_ram}+{ram} > {MAX_RAM} МБ")

    user_data = d.get("user_data") or make_user_data(hostname, d.get("ssh_key"), d.get("password"))
    meta_data = f"instance-id: {name}\nlocal-hostname: {hostname}\n"

    os.makedirs(VM_DIR, exist_ok=True)
    disk = os.path.join(VM_DIR, f"{name}.qcow2")
    seed = os.path.join(VM_DIR, f"{name}-seed.iso")
    try:
        run("qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", BASE_IMAGE, disk, f"{disk_gb}G")
        with tempfile.TemporaryDirectory() as tmp:
            ud, md = os.path.join(tmp, "user-data"), os.path.join(tmp, "meta-data")
            with open(ud, "w") as f:
                f.write(user_data)
            with open(md, "w") as f:
                f.write(meta_data)
            run("cloud-localds", seed, ud, md)
        run("virt-install", "--name", name, "--memory", str(ram), "--vcpus", str(cpu),
            "--disk", f"path={disk},format=qcow2",
            "--disk", f"path={seed},device=cdrom",
            "--import", "--os-variant", OS_VARIANT,
            "--network", "network=default",
            "--graphics", "none", "--noautoconsole")
    except Exception:
        for f in (disk, seed):
            if os.path.exists(f):
                os.remove(f)
        raise
    return jsonify(vm_info(name)), 201


@app.post("/vms/<name>/start")
def start_vm(name):
    require_vm(name)
    virsh("start", name)
    return jsonify(vm_info(name))


@app.post("/vms/<name>/stop")
def stop_vm(name):
    require_vm(name)
    virsh("destroy", name)
    return jsonify(vm_info(name))


@app.delete("/vms/<name>")
def delete_vm(name):
    require_vm(name)
    try:
        virsh("destroy", name)
    except RuntimeError:
        pass
    virsh("undefine", name)
    for f in (f"{name}.qcow2", f"{name}-seed.iso"):
        p = os.path.join(VM_DIR, f)
        if os.path.exists(p):
            os.remove(p)
    return jsonify(deleted=name)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
