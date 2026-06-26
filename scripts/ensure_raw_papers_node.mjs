import fs from "node:fs/promises";
import path from "node:path";

const VERSION = "1.0.0";
const USAGE = [
  "Usage: node ensure_raw_papers_node.mjs --manifest <batch_manifest.json> [options]",
  "",
  "Options:",
  "  --raw-dir <dir>              Raw PDF directory. Default: raw_papers",
  "  --download                   Download missing PDFs. Without this flag the script runs in dry-run mode.",
  "  --dry-run                    Do not download missing PDFs.",
  "  --no-status-write            Do not create rawDir or write <batch>_raw_status.json.",
  "  --allow-write                Explicitly allow status-file and PDF writes.",
  "  --allow-network              Explicitly allow network downloads.",
  "  --concurrency <n>            Worker count. Default: 4",
  "  --retries <n>                Download retries. Default: 3",
  "  --timeout-ms <n>             Fetch timeout. Default: 60000",
  "  --delay-ms <n>               Delay between attempts. Default: 300",
  "  --min-bytes <n>              Minimum valid PDF size. Default: 20000",
  "  --quiet                      Reduce progress output.",
  "  --no-version-fallback        Disable fallback from versioned PDF URL to base arXiv PDF URL.",
  "  --help                       Show this help and exit.",
  "  --version                    Show script version and exit.",
].join("\n");

function argValue(name, fallback = null) {
  const idx = process.argv.indexOf(name);
  if (idx >= 0 && idx + 1 < process.argv.length) return process.argv[idx + 1];
  return fallback;
}

function hasFlag(name) {
  return process.argv.includes(name);
}

function intArg(name, fallback) {
  const value = argValue(name);
  if (value === null) return fallback;
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < 0) {
    throw new Error(`${name} must be a non-negative integer`);
  }
  return parsed;
}

if (hasFlag("--help") || hasFlag("-h")) {
  console.log(USAGE);
  process.exit(0);
}

if (hasFlag("--version")) {
  console.log(`ensure_raw_papers_node.mjs ${VERSION}`);
  process.exit(0);
}

const manifestPath = argValue("--manifest");
if (!manifestPath) {
  console.error(USAGE);
  process.exit(2);
}

const rawDir = argValue("--raw-dir", "raw_papers");
const download = hasFlag("--download");
const dryRun = hasFlag("--dry-run") || !download;
const concurrency = Math.max(1, intArg("--concurrency", 4));
const retries = Math.max(1, intArg("--retries", 3));
const timeoutMs = Math.max(1000, intArg("--timeout-ms", 60000));
const delayMs = intArg("--delay-ms", 300);
const minBytes = Math.max(1024, intArg("--min-bytes", 20000));
const quiet = hasFlag("--quiet");
const versionFallback = !hasFlag("--no-version-fallback");
const noStatusWrite = hasFlag("--no-status-write");
const allowWrite = hasFlag("--allow-write");
const allowNetwork = hasFlag("--allow-network");

if (!noStatusWrite && !allowWrite) {
  console.error("Error: status-file output requires explicit --allow-write. Use --no-status-write for a pure check.");
  process.exit(2);
}
if (download && (!allowWrite || !allowNetwork)) {
  console.error("Error: downloads require --download --allow-network --allow-write.");
  process.exit(2);
}

const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
const batch = path.basename(manifestPath).replace(/_manifest\.json$/u, "");
const statusPath = path.join(rawDir, `${batch}_raw_status.json`);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function versionFromUrl(pdfUrl) {
  const match = String(pdfUrl || "").match(/(\d{4}\.\d{4,5})v(\d+)/u);
  return match ? `v${match[2]}` : "";
}

function rawTarget(row) {
  const version = versionFromUrl(row.pdf_url);
  return path.join(rawDir, `${row.arxiv_id}${version}.pdf`);
}

function candidateUrls(row) {
  const urls = [row.pdf_url];
  if (versionFallback) {
    const fallback = `https://arxiv.org/pdf/${row.arxiv_id}`;
    if (fallback !== row.pdf_url) urls.push(fallback);
  }
  return urls;
}

async function validatePdf(filePath) {
  const stat = await fs.stat(filePath).catch(() => null);
  if (!stat) return { valid: false, reason: "missing", bytes: 0 };
  if (stat.size < minBytes) return { valid: false, reason: `too_small:${stat.size}`, bytes: stat.size };

  const handle = await fs.open(filePath, "r");
  try {
    const buffer = Buffer.alloc(5);
    await handle.read(buffer, 0, 5, 0);
    if (buffer.toString("latin1") !== "%PDF-") {
      return { valid: false, reason: "not_pdf_header", bytes: stat.size };
    }
  } finally {
    await handle.close();
  }
  return { valid: true, reason: "ok", bytes: stat.size };
}

async function listRawPdfCandidates(arxivId) {
  const entries = await fs.readdir(rawDir, { withFileTypes: true }).catch(() => []);
  const candidates = [];
  for (const entry of entries) {
    if (!entry.isFile()) continue;
    if (!entry.name.toLowerCase().endsWith(".pdf")) continue;
    if (!entry.name.includes(arxivId)) continue;
    const fullPath = path.join(rawDir, entry.name);
    const validation = await validatePdf(fullPath);
    candidates.push({ path: fullPath, name: entry.name, ...validation });
  }
  return candidates;
}

async function bestExisting(row) {
  const candidates = await listRawPdfCandidates(row.arxiv_id);
  const valid = candidates.filter((item) => item.valid);
  if (valid.length === 0) {
    return {
      found: false,
      invalid_candidates: candidates.filter((item) => !item.valid),
      multiple_candidates: false,
    };
  }
  const version = versionFromUrl(row.pdf_url);
  valid.sort((a, b) => {
    const aVersion = version && a.name.includes(`${row.arxiv_id}${version}`) ? 1 : 0;
    const bVersion = version && b.name.includes(`${row.arxiv_id}${version}`) ? 1 : 0;
    if (aVersion !== bVersion) return bVersion - aVersion;
    return b.bytes - a.bytes;
  });
  return {
    found: true,
    candidate: valid[0],
    multiple_candidates: valid.length > 1,
  };
}

async function fetchWithTimeout(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      headers: { "User-Agent": "literature-research-workflow/raw/1.0" },
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

class DownloadError extends Error {
  constructor(status, message) {
    super(message);
    this.name = "DownloadError";
    this.status = status;
  }
}

async function downloadOnce(row, url, attempt) {
  const target = rawTarget(row);
  const partPath = `${target}.part`;
  const warnings = [];
  await fs.mkdir(path.dirname(target), { recursive: true });

  let response;
  try {
    response = await fetchWithTimeout(url);
  } catch (error) {
    throw new DownloadError("download_failed", String(error?.message ?? error));
  }
  if (!response.ok) throw new DownloadError("download_failed", `HTTP ${response.status}`);

  const contentType = response.headers.get("content-type") || "";
  const buffer = Buffer.from(await response.arrayBuffer());
  if (contentType.includes("html") || buffer.slice(0, 64).toString("latin1").includes("<html")) {
    throw new DownloadError("download_failed", `non_pdf_response:${contentType || "unknown"}`);
  }

  await fs.writeFile(partPath, buffer);
  const partValidation = await validatePdf(partPath);
  if (!partValidation.valid) {
    await fs.rm(partPath, { force: true }).catch((error) => {
      warnings.push(`part_cleanup_failed:${error?.message ?? error}`);
    });
    throw new DownloadError("invalid_part", partValidation.reason);
  }

  try {
    await fs.copyFile(partPath, target);
  } catch (error) {
    throw new DownloadError("finalize_failed", String(error?.message ?? error));
  }

  const finalValidation = await validatePdf(target);
  if (!finalValidation.valid) {
    throw new DownloadError("invalid_final_pdf", finalValidation.reason);
  }

  await fs.rm(partPath, { force: true }).catch((error) => {
    warnings.push(`part_cleanup_failed:${error?.message ?? error}`);
  });

  return {
    arxiv_id: row.arxiv_id,
    status: "downloaded",
    pdf_url: row.pdf_url,
    final_url: url,
    raw_path: target,
    bytes: finalValidation.bytes,
    attempts: attempt,
    validated: true,
    multiple_candidates: false,
    error: null,
    warnings,
  };
}

async function processRow(row) {
  const existing = await bestExisting(row);
  if (existing.found) {
    return {
      arxiv_id: row.arxiv_id,
      status: "exists",
      pdf_url: row.pdf_url,
      final_url: null,
      raw_path: existing.candidate.path,
      bytes: existing.candidate.bytes,
      attempts: 0,
      validated: true,
      multiple_candidates: existing.multiple_candidates,
      error: null,
      warnings: [],
    };
  }

  if (dryRun) {
    return {
      arxiv_id: row.arxiv_id,
      status: existing.invalid_candidates.length ? "invalid_existing" : "missing",
      pdf_url: row.pdf_url,
      final_url: null,
      raw_path: rawTarget(row),
      bytes: 0,
      attempts: 0,
      validated: false,
      multiple_candidates: false,
      error: existing.invalid_candidates.map((item) => `${item.name}:${item.reason}`).join("; ") || null,
      warnings: [],
    };
  }

  const urls = candidateUrls(row);
  let lastStatus = "download_failed";
  let lastError = null;
  let attempt = 0;
  for (let round = 1; round <= retries; round += 1) {
    for (const url of urls) {
      attempt += 1;
      try {
        const result = await downloadOnce(row, url, attempt);
        if (!quiet) console.error(`${row.arxiv_id}: downloaded ${result.bytes} bytes`);
        return result;
      } catch (error) {
        lastStatus = error?.status || "download_failed";
        lastError = String(error?.message ?? error);
        await fs.rm(`${rawTarget(row)}.part`, { force: true }).catch(() => {});
        if (!quiet) console.error(`${row.arxiv_id}: attempt ${attempt} failed: ${lastError}`);
      }
    }
    if (round < retries && delayMs > 0) await sleep(delayMs * round);
  }

  return {
    arxiv_id: row.arxiv_id,
    status: lastStatus,
    pdf_url: row.pdf_url,
    final_url: null,
    raw_path: rawTarget(row),
    bytes: 0,
    attempts: attempt,
    validated: false,
    multiple_candidates: false,
    error: lastError,
    warnings: [],
  };
}

async function runPool(rows, limit) {
  const results = new Array(rows.length);
  let next = 0;

  async function worker() {
    while (next < rows.length) {
      const idx = next;
      next += 1;
      results[idx] = await processRow(rows[idx]);
      if (delayMs > 0) await sleep(delayMs);
    }
  }

  const workers = [];
  const workerCount = Math.min(limit, rows.length);
  for (let i = 0; i < workerCount; i += 1) workers.push(worker());
  await Promise.all(workers);
  return results;
}

const results = await runPool(manifest, concurrency);
let statusWritten = false;
if (!noStatusWrite) {
  await fs.mkdir(rawDir, { recursive: true });
  await fs.writeFile(statusPath, JSON.stringify(results, null, 2), "utf8");
  statusWritten = true;
}

const counts = results.reduce((acc, item) => {
  acc[item.status] = (acc[item.status] || 0) + 1;
  return acc;
}, {});
const blockingStatuses = ["download_failed", "invalid_existing", "invalid_part", "finalize_failed", "invalid_final_pdf"];
const failedRows = results.filter((item) => blockingStatuses.includes(item.status));
const warningCount = results.reduce((total, item) => total + (item.warnings?.length || 0), 0);
const summary = {
  batch,
  expected: results.length,
  exists: counts.exists || 0,
  missing: counts.missing || 0,
  downloaded: counts.downloaded || 0,
  invalid_existing: counts.invalid_existing || 0,
  download_failed: counts.download_failed || 0,
  invalid_part: counts.invalid_part || 0,
  finalize_failed: counts.finalize_failed || 0,
  invalid_final_pdf: counts.invalid_final_pdf || 0,
  failed: failedRows.length,
  warnings: warningCount,
  multiple_candidates: results.filter((item) => item.multiple_candidates).length,
  status_path: statusPath,
  status_written: statusWritten,
};
if (failedRows.length > 0) {
  summary.failed_items = failedRows.map((item) => ({
    arxiv_id: item.arxiv_id,
    status: item.status,
    error: item.error,
  }));
}

console.log(JSON.stringify(summary));
