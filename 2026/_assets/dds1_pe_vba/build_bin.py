import struct, olefile, os
from oletools.olevba import decompress_stream
from ms_ovba_compression.ms_ovba import MsOvba
from ms_cfb.ole_file import OleFile
from ms_cfb.Models.Directories.root_directory import RootDirectory
from ms_cfb.Models.Directories.storage_directory import StorageDirectory
from ms_cfb.Models.Directories.stream_directory import StreamDirectory

SRC = "/tmp/vbaProject-Compiler/tests/blank/vbaProject.bin"
o = olefile.OleFileIO(SRC)
rd = lambda p: o.openstream(p).read()
dirRaw = decompress_stream(bytearray(rd("VBA/dir")))

# walk dir records; zero every MODULEOFFSET so modules are source-only (no p-code)
out, i, offsets = bytearray(), 0, {}
curName = None
while i < len(dirRaw):
    rid, size = struct.unpack_from("<HI", dirRaw, i)
    if rid == 0x0009:            # PROJECTVERSION: size field 4 but 6 data bytes
        size = 6
    data = dirRaw[i + 6:i + 6 + size]
    if rid == 0x0019:            # MODULENAME
        curName = bytes(data).decode("latin-1")
    if rid == 0x0031:            # MODULEOFFSET
        offsets[curName] = struct.unpack("<I", data)[0]
        data = struct.pack("<I", 0)
    out += struct.pack("<HI", rid, 4 if rid == 0x0009 else size) + data
    i += 6 + size
print("offsets", offsets)
comp = MsOvba()

def srcOf(name):
    raw = rd(f"VBA/{name}")
    return bytes(decompress_stream(bytearray(raw[offsets[name]:])))

code = open("ThisWorkbook_code.vba", "rb").read().replace(b"\n", b"\r\n")
sources = {n: srcOf(n) for n in offsets}
for n, s in sources.items():
    print("----", n); print(s.decode("latin-1"))
sources["ThisWorkbook"] = sources["ThisWorkbook"].rstrip(b"\r\n") + b"\r\n" + code

os.makedirs("streams", exist_ok=True)
files = {}
for n, s in sources.items():
    files[n] = f"streams/{n}.bin"; open(files[n], "wb").write(comp.compress(s))
open("streams/dir.bin", "wb").write(comp.compress(bytes(out)))
open("streams/_VBA_PROJECT.bin", "wb").write(b"\xCC\x61\xFF\xFF\x00\x00\x00")   # version 0xFFFF → recompile from source
open("streams/PROJECT.bin", "wb").write(rd("PROJECT"))
open("streams/PROJECTwm.bin", "wb").write(rd("PROJECTwm"))

root = RootDirectory()
vba = StorageDirectory("VBA")
for n in sources:
    vba.add_directory(StreamDirectory(n, files[n]))
vba.add_directory(StreamDirectory("dir", "streams/dir.bin"))
vba.add_directory(StreamDirectory("_VBA_PROJECT", "streams/_VBA_PROJECT.bin"))
root.add_directory(vba)
root.add_directory(StreamDirectory("PROJECTwm", "streams/PROJECTwm.bin"))
root.add_directory(StreamDirectory("PROJECT", "streams/PROJECT.bin"))
f = OleFile(); f.root_directory = root; f.create_file("vbaProject.bin")
print("written", os.path.getsize("vbaProject.bin"))
