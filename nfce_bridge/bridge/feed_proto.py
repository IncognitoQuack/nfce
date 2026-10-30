"""Upstox Market Data Feed V3 messages, built at runtime from the official .proto (no protoc, no generated code).

Source: https://assets.upstox.com/feed/market-data-feed/v3/MarketDataFeed.proto (linked from Upstox's V3 feed docs),
saved as bridge/proto/MarketDataFeedV3.proto, SHA-256 3e1c939dce2c83a3fef91405c5ca268dfa089aae973319f56685f12a5afcf612.

`parse()` reads the small proto3 subset that file uses (messages, enums, scalar / message / repeated / map fields,
oneof, the google.protobuf wrappers import) into a FileDescriptorProto; `classes()` turns it into message classes.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

PROTO = Path(__file__).with_name("proto") / "MarketDataFeedV3.proto"
PROTO_SHA256 = "3e1c939dce2c83a3fef91405c5ca268dfa089aae973319f56685f12a5afcf612"

_SCALARS = {"double": 1, "float": 2, "int64": 3, "uint64": 4, "int32": 5, "bool": 8, "string": 9, "bytes": 12,
            "uint32": 13, "sint32": 17, "sint64": 18}
_TOKEN = re.compile(r"[A-Za-z_][\w.]*|\d+|[{}<>=;,]")


def _tokens(text: str) -> list[str]:
    text = re.sub(r"//[^\n]*", "", text)
    return _TOKEN.findall(text)


def parse(text: str):
    from google.protobuf import descriptor_pb2 as d
    t = _tokens(text)
    fd = d.FileDescriptorProto(name="MarketDataFeedV3.proto", syntax="proto3")
    i = 0
    enums: set[str] = set()
    msgs: list = []

    def expect(tok):
        nonlocal i
        if t[i] != tok:
            raise ValueError(f"proto parse: expected {tok!r} at token {i}, got {t[i]!r}")
        i += 1

    def field(msg, label_repeated, typ, name, number, oneof_index=None):
        f = msg.field.add(name=name, number=int(number), json_name=name)
        f.label = 3 if label_repeated else 1
        if typ in _SCALARS:
            f.type = _SCALARS[typ]
        else:
            f.type_name = typ                      # resolved after all names are known
        if oneof_index is not None:
            f.oneof_index = oneof_index
        return f

    def message(container, name):
        nonlocal i
        m = container.add(name=name)
        msgs.append(m)
        expect("{")
        while t[i] != "}":
            if t[i] == "oneof":
                i += 1
                idx = len(m.oneof_decl)
                m.oneof_decl.add(name=t[i])
                i += 1
                expect("{")
                while t[i] != "}":
                    typ, nm, _, num = t[i], t[i + 1], t[i + 2], t[i + 3]
                    i += 5
                    field(m, False, typ, nm, num, idx)
                expect("}")
            elif t[i] == "map":
                i += 1
                expect("<")
                ktyp = t[i]
                i += 1
                expect(",")
                vtyp = t[i]
                i += 1
                expect(">")
                nm, num = t[i], t[i + 2]
                i += 4
                entry = m.nested_type.add(name=nm[0].upper() + nm[1:] + "Entry")
                entry.options.map_entry = True
                field(entry, False, ktyp, "key", 1)
                field(entry, False, vtyp, "value", 2)
                f = field(m, True, f"{m.name}.{entry.name}", nm, num)
            else:
                rep = t[i] == "repeated"
                if rep:
                    i += 1
                typ, nm, _, num = t[i], t[i + 1], t[i + 2], t[i + 3]
                i += 5
                field(m, rep, typ, nm, num)
        expect("}")

    while i < len(t):
        tok = t[i]
        if tok == "syntax":
            i += 4
        elif tok == "package":
            fd.package = t[i + 1]
            i += 3
        elif tok == "import":
            i += 1
            fd.dependency.append("google/protobuf/wrappers.proto")   # the only import in this file
            while t[i] != ";":
                i += 1
            i += 1
        elif tok == "enum":
            e = fd.enum_type.add(name=t[i + 1])
            enums.add(t[i + 1])
            i += 2
            expect("{")
            while t[i] != "}":
                e.value.add(name=t[i], number=int(t[i + 2]))
                i += 4
            expect("}")
        elif tok == "message":
            name = t[i + 1]
            i += 2
            message(fd.message_type, name)
        else:
            raise ValueError(f"proto parse: unexpected {tok!r}")

    pkg = "." + fd.package
    for m in msgs:
        for f in list(m.field) + [f for n in m.nested_type for f in n.field]:
            if f.type_name and not f.type_name.startswith("."):
                tn = f.type_name
                if tn.startswith("google.protobuf."):
                    f.type, f.type_name = 11, "." + tn
                elif tn in enums:
                    f.type, f.type_name = 14, f"{pkg}.{tn}"
                else:                                   # a message, possibly a map entry "Outer.XEntry"
                    f.type, f.type_name = 11, f"{pkg}.{tn}"
    return fd


@lru_cache(maxsize=1)
def classes() -> dict:
    """{message name: class} for every top-level message in the official file."""
    import hashlib
    from google.protobuf import descriptor_pool, message_factory
    from google.protobuf import wrappers_pb2  # noqa: F401  (registers wrappers.proto in the default pool)
    text = PROTO.read_text()
    if hashlib.sha256(PROTO.read_bytes()).hexdigest() != PROTO_SHA256:
        raise RuntimeError("MarketDataFeedV3.proto changed: re-verify against Upstox's file before decoding")
    fd = parse(text)
    pool = descriptor_pool.DescriptorPool()
    pool.AddSerializedFile(wrappers_pb2.DESCRIPTOR.serialized_pb)
    pool.Add(fd)
    return {m.name: message_factory.GetMessageClass(pool.FindMessageTypeByName(f"{fd.package}.{m.name}"))
            for m in fd.message_type}


def decode(payload: bytes):
    """One binary websocket frame → a FeedResponse message."""
    msg = classes()["FeedResponse"]()
    msg.ParseFromString(payload)
    return msg
