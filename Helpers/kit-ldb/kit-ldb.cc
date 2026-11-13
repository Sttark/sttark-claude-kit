// kit-ldb: reads and writes one value in a LevelDB folder, such as the Claude app's Local Storage.
// It uses Google's own LevelDB code, the library Chromium and Electron store Local Storage with, so a value
// it writes reads back in the app as if the app had written it. LevelDB locks its folder while a program has
// it open, so this fails (exit 3) while the Claude app runs; the Kit runs it only when the app is closed.
//
//   kit-ldb keys <folder> <hex prefix>          each key that starts with the prefix, in hex, one per line
//   kit-ldb get  <folder> <hex key>             the value in hex (exit 1 when there is no such key)
//   kit-ldb put  <folder> <hex key> <hex value> writes the value, synced to disk
#include <cstdio>
#include <string>
#include "leveldb/db.h"

static bool unhex(const std::string& h, std::string* out) {
  if (h.size() % 2) return false;
  out->clear();
  for (size_t i = 0; i < h.size(); i += 2) {
    unsigned v;
    if (sscanf(h.c_str() + i, "%2x", &v) != 1) return false;
    out->push_back(static_cast<char>(v));
  }
  return true;
}

static std::string hex(const std::string& s) {
  static const char* d = "0123456789abcdef";
  std::string o;
  for (unsigned char c : s) { o.push_back(d[c >> 4]); o.push_back(d[c & 15]); }
  return o;
}

int main(int argc, char** argv) {
  if (argc < 4) { fprintf(stderr, "usage: kit-ldb keys|get|put <folder> <hex> [hex value]\n"); return 2; }
  std::string cmd = argv[1], key;
  if (!unhex(argv[3], &key)) { fprintf(stderr, "bad hex\n"); return 2; }
  leveldb::Options o;
  o.create_if_missing = false;
  leveldb::DB* db = nullptr;
  leveldb::Status s = leveldb::DB::Open(o, argv[2], &db);
  if (!s.ok()) { fprintf(stderr, "open: %s\n", s.ToString().c_str()); return 3; }
  int rc = 0;
  if (cmd == "keys") {
    leveldb::Iterator* it = db->NewIterator(leveldb::ReadOptions());
    for (it->Seek(key); it->Valid() && it->key().starts_with(key); it->Next()) printf("%s\n", hex(it->key().ToString()).c_str());
    if (!it->status().ok()) { fprintf(stderr, "read: %s\n", it->status().ToString().c_str()); rc = 4; }
    delete it;
  } else if (cmd == "get") {
    std::string v;
    s = db->Get(leveldb::ReadOptions(), key, &v);
    if (s.IsNotFound()) rc = 1;
    else if (!s.ok()) { fprintf(stderr, "get: %s\n", s.ToString().c_str()); rc = 4; }
    else printf("%s\n", hex(v).c_str());
  } else if (cmd == "put" && argc == 5) {
    std::string v;
    if (!unhex(argv[4], &v)) { rc = 2; }
    else {
      leveldb::WriteOptions w;
      w.sync = true;
      s = db->Put(w, key, v);
      if (!s.ok()) { fprintf(stderr, "put: %s\n", s.ToString().c_str()); rc = 4; }
    }
  } else { rc = 2; }
  delete db;
  return rc;
}
