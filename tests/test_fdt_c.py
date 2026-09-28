# SPDX-License-Identifier: GPL-2.0-or-later
"""Host tests of src/fdt.c (built by `make host`), cross-checked with tools/fdt.py.

The trees mimic the shape of the mainline Apple device trees (root with
64-bit cells, /chosen with a disabled framebuffer@0, memory@800000000) but are
built here from scratch; no upstream DTB is used.
"""

import copy
import ctypes
import random
import unittest
from pathlib import Path

from tools.fdt import Node, build_dtb, parse_dtb, string, u32, u64

ROOT = Path(__file__).resolve().parents[1]
LIB_PATH = ROOT / "build/host/libportable.so"
OK, ERR_HEADER, ERR_STRUCT, ERR_NOTFOUND, ERR_NOSPACE, ERR_BADNAME, ERR_EXISTS, ERR_CELLS = (
    0, -1, -2, -3, -4, -5, -6, -7)


class Fdt(ctypes.Structure):
    _fields_ = [("buf", ctypes.POINTER(ctypes.c_uint8)), ("capacity", ctypes.c_uint32)]


class LinuxParams(ctypes.Structure):
    _fields_ = [("mem_base", ctypes.c_uint64), ("mem_size", ctypes.c_uint64),
                ("bootargs", ctypes.c_char_p),
                ("initrd_start", ctypes.c_uint64), ("initrd_end", ctypes.c_uint64),
                ("fb_base", ctypes.c_uint64), ("fb_width", ctypes.c_uint32),
                ("fb_height", ctypes.c_uint32), ("fb_stride", ctypes.c_uint32),
                ("fb_format", ctypes.c_char_p)]


def apple_like_tree(address_cells=2, size_cells=2):
    return Node("", {"#address-cells": u32(address_cells), "#size-cells": u32(size_cells),
                     "compatible": string("apple,j293") + string("apple,t8103"),
                     "model": string("test tree")}, [
        Node("chosen", {"#address-cells": u32(2), "#size-cells": u32(2), "ranges": b"",
                        "stdout-path": string("serial0")}, [
            Node("framebuffer@0", {"compatible": string("apple,simple-framebuffer") + string("simple-framebuffer"),
                                   "reg": u32(0, 0, 0, 0), "status": string("disabled")})]),
        Node("memory@800000000", {"device_type": string("memory"), "reg": u32(8, 0, 2, 0)}),
        Node("soc", {"ranges": b"", "compatible": string("simple-bus")}, [
            Node("serial@235200000", {"compatible": string("apple,s5l-uart"),
                                      "reg": u32(2, 0x35200000, 0, 0x1000), "status": string("okay")}),
            Node("interrupt-controller@23b100000", {"compatible": string("apple,t8103-aic"),
                                                    "interrupt-controller": b""}),
        ]),
    ])


class Blob:
    def __init__(self, lib, data, capacity=None):
        self.lib = lib
        self.capacity = capacity if capacity is not None else len(data) + 4096
        self.mem = (ctypes.c_uint8 * self.capacity)()
        ctypes.memmove(self.mem, data, min(len(data), self.capacity))
        self.fdt = Fdt()
        self.status = lib.fdt_open(ctypes.byref(self.fdt), self.mem, self.capacity)

    def bytes(self):
        return bytes(self.mem[:self.lib.fdt_total_size(ctypes.byref(self.fdt))])

    def find(self, path):
        return self.lib.fdt_find(ctypes.byref(self.fdt), path.encode())

    def set(self, path, name, value):
        return self.lib.fdt_set_prop(ctypes.byref(self.fdt), self.find(path), name.encode(),
                                     value, len(value))

    def delete(self, path, name):
        return self.lib.fdt_del_prop(ctypes.byref(self.fdt), self.find(path), name.encode())

    def add(self, path, name):
        return self.lib.fdt_add_subnode(ctypes.byref(self.fdt), self.find(path), name.encode())

    def tree(self):
        return parse_dtb(self.bytes())[0]


def node_at(tree, path):
    """Same matching rule as fdt_find: "name" also matches "name@unit"."""
    node = tree
    for part in [p for p in path.split("/") if p]:
        node = next(c for c in node.children
                    if c.name == part or ("@" not in part and c.name.startswith(part + "@")))
    return node


def padding_is_zero(blob):
    """Spec section 5.4: names and property values are zero-padded to 4 bytes."""
    import struct
    off_struct, _, _, _, _, _, _, size_struct = struct.unpack_from(">8I", blob, 8)
    pos, end = off_struct, off_struct + size_struct
    while pos < end:
        (tag,) = struct.unpack_from(">I", blob, pos)
        if tag == 1:
            stop = blob.index(b"\0", pos + 4)
            nxt = (stop + 1 + 3) & ~3
            if any(blob[stop:nxt]):
                return False
            pos = nxt
        elif tag == 3:
            length = struct.unpack_from(">I", blob, pos + 4)[0]
            data_end = pos + 12 + length
            nxt = (data_end + 3) & ~3
            if any(blob[data_end:nxt]):
                return False
            pos = nxt
        else:
            pos += 4
    return True


def all_paths(node, prefix=""):
    here = prefix or "/"
    yield here
    for child in node.children:
        yield from all_paths(child, f"{prefix}/{child.name}")


class FdtCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not LIB_PATH.exists():
            raise unittest.SkipTest("run `make host` first")
        lib = ctypes.CDLL(str(LIB_PATH))
        p = ctypes.POINTER(Fdt)
        lib.fdt_open.argtypes = [p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
        lib.fdt_total_size.argtypes = [p]
        lib.fdt_total_size.restype = ctypes.c_uint32
        lib.fdt_find.argtypes = [p, ctypes.c_char_p]
        lib.fdt_set_prop.argtypes = [p, ctypes.c_int, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
        lib.fdt_del_prop.argtypes = [p, ctypes.c_int, ctypes.c_char_p]
        lib.fdt_add_subnode.argtypes = [p, ctypes.c_int, ctypes.c_char_p]
        lib.fdt_fill_linux.argtypes = [p, ctypes.POINTER(LinuxParams)]
        cls.lib = lib

    def blob(self, tree=None, capacity=None, reserve=()):
        b = Blob(self.lib, build_dtb(tree or apple_like_tree(), reserve=reserve), capacity)
        self.assertEqual(b.status, OK)
        return b

    def test_find_paths(self):
        b = self.blob()
        self.assertEqual(b.find("/"), 0)
        self.assertGreater(b.find("/memory"), 0)
        self.assertEqual(b.find("/memory"), b.find("/memory@800000000"))
        self.assertEqual(b.find("/memory@1"), ERR_NOTFOUND)
        self.assertGreater(b.find("/chosen/framebuffer"), b.find("/chosen"))
        self.assertGreater(b.find("/soc/serial"), 0)
        self.assertEqual(b.find("/soc/nothing"), ERR_NOTFOUND)
        self.assertEqual(b.find("chosen"), ERR_BADNAME)

    def test_set_replace_delete_preserve_rest(self):
        b = self.blob()
        model = apple_like_tree()
        edits = [("/chosen", "bootargs", string("quiet splash")),        # new property, new string
                 ("/memory", "reg", u32(8, 0, 1, 0)),                       # same length
                 ("/chosen/framebuffer", "status", string("okay")),         # shorter
                 ("/soc/serial@235200000", "status", string("disabled-by-test"))]  # longer
        for path, name, value in edits:
            self.assertEqual(b.set(path, name, value), OK)
            node_at(model, path).props[name] = value
        self.assertEqual(b.delete("/soc", "ranges"), OK)
        del node_at(model, "/soc").props["ranges"]
        self.assertEqual(b.delete("/soc", "ranges"), ERR_NOTFOUND)
        got = b.tree()
        for path in all_paths(model):
            self.assertEqual(node_at(got, path).props, node_at(model, path).props, path)
        # Shrinking within the same 4-byte slot must not leave old bytes behind.
        self.assertEqual(b.set("/", "model", b"\xff" * 7), OK)
        self.assertEqual(b.set("/", "model", b"\x01" * 5), OK)
        self.assertTrue(padding_is_zero(b.bytes()))

    def test_exact_fit_never_writes_past_capacity(self):
        data = build_dtb(apple_like_tree())
        value = string("abcdefg")  # 8 bytes: property needs 12 + 8 bytes in the structure block
        for extra, expected in ((12 + 8, ERR_NOSPACE),                        # no room for the new name
                                (12 + 8 + len(b"brand-new-name\0"), OK)):  # exactly enough
            with self.subTest(extra=extra):
                capacity = len(data) + extra
                guarded = Blob(self.lib, data, capacity=capacity + 64)
                guarded.fdt.capacity = capacity  # the C code may only use `capacity` bytes
                for i in range(capacity, capacity + 64):
                    guarded.mem[i] = 0xA5
                before = guarded.bytes()
                self.assertEqual(guarded.set("/chosen", "brand-new-name", value), expected)
                self.assertEqual(bytes(guarded.mem[capacity:capacity + 64]), b"\xa5" * 64)
                if expected != OK:
                    self.assertEqual(guarded.bytes(), before)
                else:
                    self.assertEqual(guarded.lib.fdt_total_size(ctypes.byref(guarded.fdt)), capacity)

    def test_memory_reservations_survive_edits(self):
        b = self.blob(reserve=[(0x9E0000000, 0x800000)])
        self.assertEqual(b.set("/chosen", "bootargs", string("x" * 100)), OK)
        _, reserve, _ = parse_dtb(b.bytes())
        self.assertEqual(reserve, [(0x9E0000000, 0x800000)])

    def test_add_subnode(self):
        b = self.blob()
        self.assertGreater(b.add("/", "reserved-memory"), 0)
        self.assertEqual(b.set("/reserved-memory", "ranges", b""), OK)
        self.assertEqual(b.add("/", "reserved-memory"), ERR_EXISTS)
        self.assertEqual(b.add("/", "bad/name"), ERR_BADNAME)
        self.assertEqual(b.add("/", ""), ERR_BADNAME)
        tree = b.tree()
        self.assertEqual(tree.child("reserved-memory").props, {"ranges": b""})
        # Properties still precede child nodes in the root.
        self.assertIn("model", tree.props)

    def test_no_space_changes_nothing(self):
        data = build_dtb(apple_like_tree())
        b = Blob(self.lib, data, capacity=len(data))
        before = b.bytes()
        self.assertEqual(b.set("/chosen", "bootargs", string("does not fit")), ERR_NOSPACE)
        self.assertEqual(b.add("/", "extra"), ERR_NOSPACE)
        self.assertEqual(b.bytes(), before)
        # Shrinking always fits.
        self.assertEqual(b.set("/chosen/framebuffer", "status", string("ok")), OK)

    def test_header_rejections(self):
        data = bytearray(build_dtb(apple_like_tree()))
        self.assertEqual(Blob(self.lib, bytes(data), capacity=len(data) - 1).status, ERR_HEADER)
        bad = bytearray(data); bad[0] = 0
        self.assertEqual(Blob(self.lib, bytes(bad)).status, ERR_HEADER)
        old = bytearray(data); old[20:24] = u32(16)
        self.assertEqual(Blob(self.lib, bytes(old)).status, ERR_HEADER)
        swapped = bytearray(data); swapped[8:12], swapped[12:16] = data[12:16], data[8:12]
        self.assertNotEqual(Blob(self.lib, bytes(swapped)).status, OK)

    def fill(self, blob, **values):
        params = LinuxParams(**values)
        return self.lib.fdt_fill_linux(ctypes.byref(blob.fdt), ctypes.byref(params))

    def test_fill_linux_on_apple_like_tree(self):
        b = self.blob()
        status = self.fill(b, mem_base=0x800000000, mem_size=0x1E0000000, bootargs=b"console=tty0 quiet",
                           initrd_start=0x810000000, initrd_end=0x810800000, fb_base=0x9E0000000,
                           fb_width=2560, fb_height=1600, fb_stride=10240, fb_format=b"x2r10g10b10")
        self.assertEqual(status, OK)
        t = b.tree()
        self.assertEqual(t.child("memory@800000000").props["reg"], u64(0x800000000, 0x1E0000000))
        chosen = t.child("chosen")
        self.assertEqual(chosen.props["bootargs"], string("console=tty0 quiet"))
        self.assertEqual(chosen.props["linux,initrd-start"], u64(0x810000000))
        self.assertEqual(chosen.props["linux,initrd-end"], u64(0x810800000))
        self.assertEqual(chosen.props["stdout-path"], string("serial0"))  # untouched
        fb = chosen.child("framebuffer@0").props
        self.assertEqual(fb["reg"], u64(0x9E0000000, 10240 * 1600))
        self.assertEqual((fb["width"], fb["height"], fb["stride"]), (u32(2560), u32(1600), u32(10240)))
        self.assertEqual(fb["format"], string("x2r10g10b10"))
        self.assertEqual(fb["status"], string("okay"))
        # Everything outside the filled properties is unchanged.
        self.assertEqual(t.child("soc"), apple_like_tree().child("soc"))

    def test_fill_linux_cells_and_missing_nodes(self):
        b = self.blob(apple_like_tree(address_cells=1, size_cells=1))
        self.assertEqual(self.fill(b, mem_base=0x40000000, mem_size=0x8000000), OK)
        self.assertEqual(b.tree().child("memory@800000000").props["reg"], u32(0x40000000, 0x8000000))
        self.assertEqual(self.fill(b, mem_base=0x800000000, mem_size=0x1000), ERR_CELLS)
        tree = apple_like_tree()
        tree.children = [c for c in tree.children if c.name != "chosen"]
        b = self.blob(tree)
        self.assertEqual(self.fill(b, bootargs=b"x"), OK)  # /chosen is created
        self.assertEqual(b.tree().child("chosen").props["bootargs"], string("x"))
        self.assertEqual(self.fill(b, fb_base=0x9E0000000, fb_width=1, fb_height=1, fb_stride=4,
                                   fb_format=b"x8r8g8b8"), ERR_NOTFOUND)

    def test_randomized_edits_match_python_model(self):
        rng = random.Random(20260927)
        b = self.blob(capacity=64 * 1024)
        model = apple_like_tree()
        names = ["a", "status", "reg", "bootargs", "linux,x", "long-property-name-for-strings", "#size-cells"]
        for step in range(400):
            path = rng.choice(list(all_paths(model)))
            op = rng.random()
            if op < 0.6:
                name, value = rng.choice(names), bytes(rng.randrange(256) for _ in range(rng.randrange(0, 41)))
                self.assertEqual(b.set(path, name, value), OK, (step, path, name))
                node_at(model, path).props[name] = value
            elif op < 0.85:
                name = rng.choice(names)
                expect = OK if name in node_at(model, path).props else ERR_NOTFOUND
                self.assertEqual(b.delete(path, name), expect, (step, path, name))
                node_at(model, path).props.pop(name, None)
            else:
                name = f"n{rng.randrange(20)}"
                exists = any(c.name == name for c in node_at(model, path).children)
                result = b.add(path, name)
                if exists:
                    self.assertEqual(result, ERR_EXISTS)
                else:
                    self.assertGreaterEqual(result, 0)
                    node_at(model, path).children.insert(0, Node(name, {}))
            got = b.tree()
            self.assertTrue(padding_is_zero(b.bytes()), step)
            for p in all_paths(model):
                self.assertEqual(node_at(got, p).props, node_at(model, p).props, (step, p))
            self.assertEqual(sorted(all_paths(got)), sorted(all_paths(model)), step)


if __name__ == "__main__":
    unittest.main()
