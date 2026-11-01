#!/usr/bin/env python3
"""Patch Wine's ole32.dll for bug 60225:
RevokeDragDrop releases a drop target another process registered, so Tappo
crashes revoking WebView2's windows. Return DRAGDROP_E_INVALIDHWND for foreign windows.
"""
import hashlib
import struct
import sys

EXPECTED_SHA256 = "338998d7dc5c19c4977d2501f628463db63e89177d40558d2349f964f1352a31"
IMAGE_BASE = 0x180000000
TEXT_HEADER = 0x188
PATCH_SITE = 0x39227
CAVE = 0x58a40
INVALID_HWND_PATH = 0x39350
RESUME = 0x39238
IMP_IS_WINDOW = 0x953c0
IMP_GET_WINDOW_THREAD_PROCESS_ID = 0x953b0

ORIGINAL_SITE = bytes.fromhex('4889d9ff1590c10500' '85c0' '0f8418010000')


def rel32(target, next_instruction):
    return struct.pack('<i', target - next_instruction)


def build_cave():
    code = bytearray()

    def emit(opcode, target=None):
        code.extend(opcode)
        if target is not None:
            code.extend(rel32(target, CAVE + len(code) + 4))

    emit(bytes.fromhex('4889d9'))
    emit(bytes.fromhex('ff15'), IMP_IS_WINDOW)
    emit(bytes.fromhex('85c0'))
    emit(bytes.fromhex('0f84'), INVALID_HWND_PATH)
    emit(bytes.fromhex('c744243000000000'))
    emit(bytes.fromhex('4889d9'))
    emit(bytes.fromhex('488d542430'))
    emit(bytes.fromhex('ff15'), IMP_GET_WINDOW_THREAD_PROCESS_ID)
    emit(bytes.fromhex('65488b042530000000'))
    emit(bytes.fromhex('8b4040'))
    emit(bytes.fromhex('3b442430'))
    emit(bytes.fromhex('0f85'), INVALID_HWND_PATH)
    emit(bytes.fromhex('e9'), RESUME)
    return bytes(code)


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <source_ole32.dll> <dest_ole32.dll>")
        sys.exit(1)
    source, destination = sys.argv[1], sys.argv[2]
    data = bytearray(open(source, 'rb').read())

    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_SHA256:
        # Check if already patched
        cave = build_cave()
        if data[CAVE:CAVE + len(cave)] == cave:
            print("[patch_ole32] Already patched.")
            if source != destination:
                open(destination, 'wb').write(data)
            return 0
        sys.exit(f'unexpected ole32.dll ({digest}), offsets would be wrong')

    if data[PATCH_SITE:PATCH_SITE + len(ORIGINAL_SITE)] != ORIGINAL_SITE:
        sys.exit('patch site does not match')

    cave = build_cave()
    if any(data[CAVE:CAVE + len(cave) + 16]):
        sys.exit('cave is not empty')
    data[CAVE:CAVE + len(cave)] = cave

    site = bytes.fromhex('e9') + rel32(CAVE, PATCH_SITE + 5)
    site += b'\x90' * (len(ORIGINAL_SITE) - len(site))
    data[PATCH_SITE:PATCH_SITE + len(site)] = site

    text_vsize = struct.unpack_from('<I', data, TEXT_HEADER + 8)[0]
    needed = (CAVE + len(cave) - 0x1000 + 0xf) & ~0xf
    if needed > text_vsize:
        struct.pack_into('<I', data, TEXT_HEADER + 8, needed)

    # Without the builtin signature Wine treats the file as a native DLL instead of swapping in its own copy.
    if data[0x40:0x50] == b'Wine builtin DLL':
        data[0x40:0x50] = b'\0' * 16

    open(destination, 'wb').write(data)
    print(f'[patch_ole32] Successfully patched {destination}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
