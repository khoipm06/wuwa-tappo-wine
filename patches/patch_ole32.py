#!/usr/bin/env python3
"""Patch Proton's ole32.dll: RevokeDragDrop -> return S_OK (xor eax,eax; ret).

WineHQ bug 60225: Tauri's drag-drop lifetime registers the drop target from the
WebView2 browser process but revokes it from the app process. Wine's ole32
dereferences the foreign-process pointer and faults (c0000005) on the main
thread, killing the app silently. Nulling RevokeDragDrop is safe: the OS-level
cleanup is skipped, and the process is exiting anyway.

The patcher is defensive:
  * locates RevokeDragDrop through the PE export table (no hardcoded offsets),
  * verifies the expected stock prologue before touching anything,
  * idempotent re-runs are no-ops,
  * refuses DLLs whose architecture/size look unexpected.

Usage: patch_ole32.py <path-to-Proton>/files/lib/wine/x86_64-windows/ole32.dll
"""
import hashlib
import shutil
import struct
import sys

# Stock DW-Proton 10.x / GE / CachyOS x86_64 ole32.dll RevokeDragDrop prologue
# (push rbp; push r13; push r12; push rdi; push rsi; push rbx; sub rsp,0x48...)
EXPECTED_PROLOGUE = bytes.fromhex("55415541545756534883ec48")
PATCH = bytes.fromhex("31c0c3")  # xor eax, eax; ret  (NTSTATUS/S_OK = 0)


def rva2off(data, rva):
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\x00\x00":
        raise ValueError("not a PE file")
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    opt = pe + 24
    if struct.unpack_from("<H", data, opt)[0] != 0x20B:
        raise ValueError("not PE32+ (x86_64)")
    sec = opt + struct.unpack_from("<H", data, pe + 20)[0]
    for i in range(nsec):
        s = sec + i * 40
        vsz, va, rsz, raw = struct.unpack_from("<IIII", data, s + 8)
        if va <= rva < va + max(vsz, rsz):
            return raw + (rva - va)
    raise ValueError(f"RVA {rva:#x} not mapped")


def export_rva(data, name):
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    opt = pe + 24
    sec = opt + struct.unpack_from("<H", data, pe + 20)[0]
    exp_rva, _ = struct.unpack_from("<II", data, opt + 112)
    eo = rva2off(data, exp_rva)
    nfuncs, nnames = struct.unpack_from("<II", data, eo + 20)
    names_off = rva2off(data, struct.unpack_from("<I", data, eo + 32)[0])
    funcs_off = rva2off(data, struct.unpack_from("<I", data, eo + 28)[0])
    for i in range(nnames):
        nrva = struct.unpack_from("<I", data, names_off + i * 4)[0]
        no = rva2off(data, nrva)
        end = data.index(b"\x00", no)
        if data[no:end].decode() == name:
            ordi = struct.unpack_from("<H", data, names_off + nfuncs * 4 + i * 2)[0]
            return struct.unpack_from("<I", data, funcs_off + ordi * 4)[0]
    raise ValueError(f"export {name} not found")


def main(path):
    data = open(path, "rb").read()
    if len(data) < 0x100000 or len(data) > 0x400000:
        sys.exit(f"refusing odd file size {len(data)}")
    rva = export_rva(data, "RevokeDragDrop")
    off = rva2off(data, rva)
    cur = data[off:off + len(EXPECTED_PROLOGUE)]
    if cur.startswith(PATCH):
        print(f"already patched: {path}")
        print(f"  RevokeDragDrop RVA {rva:#x} off {off:#x} = {PATCH.hex()}")
        return 0
    if cur != EXPECTED_PROLOGUE:
        sys.exit(
            f"unexpected prologue at RevokeDragDrop (off {off:#x}):\n"
            f"  found    {cur.hex()}\n"
            f"  expected {EXPECTED_PROLOGUE.hex()}\n"
            "This ole32.dll build is not supported; refusing to patch."
        )
    # Direct in-place patch without backup (user requested no backups)
    import os, stat as st
    mode = os.stat(path).st_mode
    if not mode & st.S_IWUSR:
        os.chmod(path, mode | st.S_IWUSR)  # Proton installs read-only; restore later
    try:
        with open(path, "r+b") as f:
            f.seek(off)
            f.write(PATCH)
    finally:
        if not mode & st.S_IWUSR:
            os.chmod(path, mode)
    # verify
    chk = open(path, "rb").read()
    assert chk[off:off + 3] == PATCH, "verification failed"
    print(f"patched: {path}")
    print(f"  RevokeDragDrop RVA {rva:#x} off {off:#x}: {cur[:3].hex()} -> {PATCH.hex()}")
    print(f"  sha256: {hashlib.sha256(chk).hexdigest()}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
