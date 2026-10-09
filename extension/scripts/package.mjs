#!/usr/bin/env node
/**
 * Zip the built extension (dist/) for members to install with "Load unpacked".
 *
 *   node scripts/package.mjs [outDir]      (default outDir: extension/release)
 *
 * Writes <outDir>/jobbot-copilot.zip and <outDir>/jobbot-copilot.json (version,
 * size, sha256, build time, API origin) — the web app's /download page reads the
 * JSON. The zip holds one top-level "jobbot-copilot/" folder containing
 * manifest.json, so members get a clearly named folder when they unzip it.
 *
 * Plain Node (zlib + a minimal ZIP writer) so it runs the same on Windows,
 * macOS and the Linux Docker build without extra tools.
 */
import { createHash } from "node:crypto";
import { mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { deflateRawSync } from "node:zlib";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const distDir = path.join(root, "dist");
const outDir = path.resolve(process.argv[2] || path.join(root, "release"));
const FOLDER = "jobbot-copilot";
const BASENAME = "jobbot-copilot";

const manifestPath = path.join(distDir, "manifest.json");
let manifest;
try {
  manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
} catch {
  console.error(`No built extension at ${manifestPath} — run "npm run build" first.`);
  process.exit(1);
}

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
function crc32(buf) {
  let c = 0xffffffff;
  for (const byte of buf) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function dosDateTime(d) {
  const time = (d.getHours() << 11) | (d.getMinutes() << 5) | Math.floor(d.getSeconds() / 2);
  const date = ((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate();
  return { time, date };
}

function buildZip(files) {
  const { time, date } = dosDateTime(new Date());
  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const { name, data } of files) {
    const nameBuf = Buffer.from(name, "utf8");
    const compressed = deflateRawSync(data, { level: 9 });
    const crc = crc32(data);

    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4); // version needed
    local.writeUInt16LE(0x0800, 6); // UTF-8 names
    local.writeUInt16LE(8, 8); // deflate
    local.writeUInt16LE(time, 10);
    local.writeUInt16LE(date, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(compressed.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(nameBuf.length, 26);
    locals.push(local, nameBuf, compressed);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4); // made by
    central.writeUInt16LE(20, 6); // needed
    central.writeUInt16LE(0x0800, 8);
    central.writeUInt16LE(8, 10);
    central.writeUInt16LE(time, 12);
    central.writeUInt16LE(date, 14);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(compressed.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(nameBuf.length, 28);
    central.writeUInt32LE(offset, 42);
    centrals.push(central, nameBuf);

    offset += local.length + nameBuf.length + compressed.length;
  }
  const centralBuf = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(files.length, 8);
  end.writeUInt16LE(files.length, 10);
  end.writeUInt32LE(centralBuf.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, centralBuf, end]);
}

const files = walk(distDir)
  .map((full) => ({
    name: `${FOLDER}/${path.relative(distDir, full).split(path.sep).join("/")}`,
    data: readFileSync(full),
  }))
  .sort((a, b) => a.name.localeCompare(b.name));
const zip = buildZip(files);

// The API origin this build talks to — useful to spot a zip built for the wrong server.
const apiOrigin = (manifest.host_permissions || [])[0]?.replace(/\/\*$/, "") || "";

mkdirSync(outDir, { recursive: true });
writeFileSync(path.join(outDir, `${BASENAME}.zip`), zip);
const info = {
  name: manifest.name,
  version: manifest.version,
  filename: `${BASENAME}-${manifest.version}.zip`,
  size: zip.length,
  sha256: createHash("sha256").update(zip).digest("hex"),
  built_at: new Date().toISOString(),
  api_origin: apiOrigin,
  files: files.length,
};
writeFileSync(path.join(outDir, `${BASENAME}.json`), `${JSON.stringify(info, null, 2)}\n`);
console.log(`Packaged ${info.name} ${info.version} (${files.length} files, ${(zip.length / 1024).toFixed(0)} KB) -> ${outDir}`);
console.log(`Server: ${apiOrigin}`);
