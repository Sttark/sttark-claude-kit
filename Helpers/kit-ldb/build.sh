#!/bin/zsh
# Builds kit-ldb (see kit-ldb.cc) as one program for Apple Silicon and Intel Macs, into $1.
# LevelDB and Snappy come from Google's tagged releases, checked against the hashes below before use.
set -e
cd "$(dirname "$0")"
OUT=${1:?output path}
SRC=${KIT_LDB_SRC:-${TMPDIR:-/tmp}/kit-ldb-src}
mkdir -p "$SRC"
get() { # name url sha256
  local f="$SRC/$1.tgz"
  [[ -f $f ]] && [[ $(shasum -a 256 "$f" | cut -d' ' -f1) == $3 ]] || curl -fsSL -o "$f" "$2"
  [[ $(shasum -a 256 "$f" | cut -d' ' -f1) == $3 ]] || { echo "kit-ldb: $1 download does not match its hash"; exit 1; }
  rm -rf "$SRC/$1" && mkdir -p "$SRC/$1" && tar xzf "$f" -C "$SRC/$1" --strip-components 1
}
get leveldb https://github.com/google/leveldb/archive/refs/tags/1.23.tar.gz 9a37f8a6174f09bd622bc723b55881dc541cd50747cbd08831c2a82d620f6d76
get snappy https://github.com/google/snappy/archive/refs/tags/1.2.1.tar.gz 736aeb64d86566d2236ddffa2865ee5d7a82d26c9016b36218fcc27ea4f09f86
L=$SRC/leveldb S=$SRC/snappy G=$SRC/gen
mkdir -p $G/port
sed -e 's/${HAVE_SYS_UIO_H_01}/1/' -e 's/${PROJECT_VERSION_MAJOR}/1/' -e 's/${PROJECT_VERSION_MINOR}/2/' \
    -e 's/${PROJECT_VERSION_PATCH}/1/' $S/snappy-stubs-public.h.in > $G/snappy-stubs-public.h
printf '#define HAVE_FDATASYNC 0\n#define HAVE_FULLFSYNC 1\n#define HAVE_O_CLOEXEC 1\n#define HAVE_CRC32C 0\n#define HAVE_SNAPPY 1\n' > $G/port/port_config.h
FILES=($S/snappy.cc $S/snappy-sinksource.cc $S/snappy-stubs-internal.cc kit-ldb.cc)
for f in $L/db/*.cc $L/table/*.cc $L/util/*.cc; do
  [[ $f == *_test.cc || $f == *bench* || $f == *env_windows* || $f == *testutil* || $f == */leveldbutil.cc || $f == */c.cc ]] || FILES+=$f
done
for arch in arm64 x86_64; do
  clang++ -std=c++17 -O2 -w -target $arch-apple-macos14.0 -DLEVELDB_PLATFORM_POSIX=1 -DNDEBUG \
    -I$G -I$L -I$L/include -I$S $FILES -o "$OUT-$arch"
done
lipo -create "$OUT-arm64" "$OUT-x86_64" -output "$OUT"
rm "$OUT-arm64" "$OUT-x86_64"
