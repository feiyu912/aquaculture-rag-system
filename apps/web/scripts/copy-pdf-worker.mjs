#!/usr/bin/env node
/**
 * Copy the pdf.js runtime, worker and data files into `public/`.
 *
 * pdf.js ships a webpack bundle. When Next.js bundles it a second time the
 * inner runtime breaks (`Object.defineProperty called on non-object`), so the
 * library is loaded as a plain ES module from `public/` instead. The worker is
 * loaded as a module worker from the same place.
 *
 * `cmaps/` and `standard_fonts/` are required as well: without them pdf.js
 * cannot map CJK encodings and the rendered page comes out blank.
 */
import { cpSync, copyFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");

const files = [
  ["node_modules/pdfjs-dist/build/pdf.min.mjs", "public/pdf.min.mjs"],
  ["node_modules/pdfjs-dist/build/pdf.worker.min.mjs", "public/pdf.worker.min.mjs"],
];

const directories = [
  ["node_modules/pdfjs-dist/cmaps", "public/cmaps"],
  ["node_modules/pdfjs-dist/standard_fonts", "public/standard_fonts"],
];

mkdirSync(path.join(root, "public"), { recursive: true });

for (const [from, to] of files) {
  copyFileSync(path.join(root, from), path.join(root, to));
  console.log(`copied ${from} -> ${to}`);
}

for (const [from, to] of directories) {
  cpSync(path.join(root, from), path.join(root, to), { recursive: true });
  console.log(`copied ${from} -> ${to}`);
}
