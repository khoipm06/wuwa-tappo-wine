#!/usr/bin/env python3
"""Align PE sections to 4KB boundaries and clear ASLR (DYNAMIC_BASE).

Wine can only mmap shared PE sections when they align to 4KB page boundaries.
msedge.dll defaults to 512-byte boundaries, forcing all 11 WebView2 renderer
processes to allocate private 335MB copies (ballooning RAM to 8GB).
Realigning to 4KB allows Wine to share mmap pages across all renderers,
dropping memory usage from 8GB to ~1.5GB.
"""
import glob
import os
import struct
import sys

PAGE = 0x1000
SECURITY_DIRECTORY = 4
DEBUG_DIRECTORY = 6
IMAGE_FILE_DLL = 0x2000
DYNAMIC_BASE = 0x40


def align_up(val, align):
    return (val + align - 1) & ~(align - 1)


def parse(data):
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    if data[pe:pe + 4] != b'PE\0\0':
        return None
    opt = pe + 24
    opt_size = struct.unpack_from('<H', data, pe + 20)[0]
    magic = struct.unpack_from('<H', data, opt)[0]
    return {
        'pe': pe,
        'optional': opt,
        'sections_at': opt + opt_size,
        'section_count': struct.unpack_from('<H', data, pe + 6)[0],
        'characteristics': struct.unpack_from('<H', data, pe + 22)[0],
        'directories': opt + (112 if magic == 0x20B else 96),
        'section_alignment': struct.unpack_from('<I', data, opt + 32)[0],
        'file_alignment': struct.unpack_from('<I', data, opt + 36)[0],
        'headers_size': struct.unpack_from('<I', data, opt + 60)[0],
        'dll_characteristics': struct.unpack_from('<H', data, opt + 70)[0],
    }


def section_headers(data, layout):
    for i in range(layout['section_count']):
        at = layout['sections_at'] + i * 40
        vsz, va, rsz, raw = struct.unpack_from('<IIII', data, at + 8)
        yield at, vsz, va, rsz, raw


def is_aligned(data, layout):
    if layout['file_alignment'] < PAGE:
        return False
    return all(not rsz or raw % PAGE == 0 for _, _, _, rsz, raw in section_headers(data, layout))


def pe_checksum(data):
    step = 1 << 20
    view = memoryview(data)
    total = sum(int.from_bytes(view[s:s + step], 'little') % 0xFFFF for s in range(0, len(data), step))
    folded = total % 0xFFFF or 0xFFFF
    return (folded + len(data)) & 0xFFFFFFFF


def realign(data, layout):
    if layout['section_alignment'] < PAGE:
        return None
    secs = sorted((raw, rsz, at) for at, _, _, rsz, raw in section_headers(data, layout) if rsz and raw)
    if not secs or secs[0][0] < layout['headers_size']:
        return None
    for (p, s, _), (np, _, _) in zip(secs, secs[1:]):
        if p + s > np:
            return None

    hdr_size = align_up(layout['headers_size'], PAGE)
    out = bytearray(data[:layout['headers_size']])
    out += bytes(hdr_size - len(out))
    moves = []
    for p, s, at in secs:
        moves.append((p, p + s, len(out)))
        struct.pack_into('<II', out, at + 16, align_up(s, PAGE), len(out))
        out += data[p:p + s]
        out += bytes(align_up(len(out), PAGE) - len(out))

    secs_end = secs[-1][0] + secs[-1][1]
    if secs_end < len(data):
        out += bytes(align_up(len(out), 8) - len(out))
        moves.append((secs_end, len(data), len(out)))
        out += data[secs_end:]

    def moved(offset):
        for start, end, new_start in moves:
            if start <= offset < end:
                return new_start + offset - start
        return offset

    sec_at = layout['directories'] + SECURITY_DIRECTORY * 8
    sec_off, sec_sz = struct.unpack_from('<II', data, sec_at)
    if sec_sz:
        struct.pack_into('<I', out, sec_at, moved(sec_off))

    dbg_rva, dbg_sz = struct.unpack_from('<II', data, layout['directories'] + DEBUG_DIRECTORY * 8)
    for _, _, va, rsz, raw in section_headers(data, layout):
        if dbg_sz and va <= dbg_rva < va + rsz:
            first_entry = moved(raw + dbg_rva - va)
            for entry in range(first_entry, first_entry + dbg_sz, 28):
                ptr = struct.unpack_from('<I', out, entry + 24)[0]
                if ptr:
                    struct.pack_into('<I', out, entry + 24, moved(ptr))

    struct.pack_into('<I', out, layout['optional'] + 36, PAGE)
    struct.pack_into('<I', out, layout['optional'] + 60, hdr_size)
    return out


def align_file(path):
    with open(path, 'rb') as f:
        head = f.read(PAGE)
    layout = parse(head)
    if not layout:
        return False
    wants_fixed = (layout['characteristics'] & IMAGE_FILE_DLL) and (layout['dll_characteristics'] & DYNAMIC_BASE)
    if is_aligned(head, layout) and not wants_fixed:
        return False

    data = open(path, 'rb').read()
    out = bytearray(data) if is_aligned(data, layout) else realign(data, layout)
    if out is None:
        return False

    if wants_fixed:
        struct.pack_into('<H', out, layout['optional'] + 70, layout['dll_characteristics'] & ~DYNAMIC_BASE)
    chk_at = layout['optional'] + 64
    struct.pack_into('<I', out, chk_at, 0)
    struct.pack_into('<I', out, chk_at, pe_checksum(out))

    tmp = f"{path}.align_tmp"
    with open(tmp, 'wb') as f:
        f.write(out)
    os.chmod(tmp, os.stat(path).st_mode & 0o7777)
    os.replace(tmp, path)
    return True


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <prefix_path>")
        sys.exit(1)
    prefix = sys.argv[1]
    paths = sorted(glob.glob(f"{prefix}/drive_c/Program Files (x86)/Microsoft/EdgeWebView/Application/*/msedge.dll"))
    paths.append(f"{prefix}/drive_c/Program Files/WuwaTappoGlobal/WuwaTappo.exe")
    for p in paths:
        if os.path.isfile(p):
            if align_file(p):
                print(f"[align_pe] Realigned: {p}")
            else:
                print(f"[align_pe] Already aligned: {p}")


if __name__ == "__main__":
    main()
