#!/usr/bin/env node
/**
 * Copy the pdf.js worker into `public/` so it can be served as a static
 * asset. The worker is required for rendering, and bundling it through the
 * app router is fragile — a plain static file is deterministic and works
 * offline.
 */
import { copyFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");

const source = path.join(root, "node_modules", "pdfjs-dist", "build", "pdf.worker.min.mjs");
const targetDir = path.join(root, "public");
const target = path.join(targetDir, "pdf.worker.min.mjs");

mkdirSync(targetDir, { recursive: true });
copyFileSync(source, target);
console.log(`copied pdf.js worker -> ${path.relative(root, target)}`);
