// SPDX-License-Identifier: GPL-2.0-or-later
// Darwin ARM64 variadic arguments live on the stack. Preserve absent or
// integer arguments verbatim when forwarding all unrelated ioctl requests.
.text
.globl _ch348Ioctl
.p2align 2
_ch348Ioctl:
    mov w9, #0x5402
    movk w9, #0x8008, lsl #16
    cmp x1, x9
    b.eq Lspeed
    b _ioctl
Lspeed:
    ldr x2, [sp]
    b _ch348Speed
