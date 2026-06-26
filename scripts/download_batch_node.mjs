import fs from "node:fs/promises";
import path from "node:path";

const VERSION = "1.0.0";
const USAGE = [
  "Usage: node download_batch_node.mjs --manifest <batch_manifest.json> (--validate-only | --download) [options]",
  "",
  "Options:",
  "  --validate-only              Validate existing PDFs without downloading.",
  "  --download                   Explicitly allow PDF downloads.",
  "  --no-status-write            Do not write <batch>_download_status.json.",
  "  --allow-write                Explicitly allow status-file and PDF writes.",
  "  --allow-network              Explicitly allow network downloads.",
  "  --concurrency <n>            Worker count. Default: 4",
  "  --retries <n>                Download retries. Default: 3",
  "  --timeout-ms <n>             Fetch timeout. Default: 60000",
  "  --delay-ms <n>               Delay between attempts. Default: 300",
  "  --min-bytes <n>              Minimum valid PDF size. Default: 20000",
  "  --quiet                      Reduce progress output.",
  "  --only-failed                Retry only previously failed or invalid entries.",
  "  --no-fallback-no-version     Disable fallback from versioned PDF URL to base arXiv PDF URL.",
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
  console.log(`download_batch_node.mjs ${VERSION}`);
  process.exit(0);
}

const manifestPath = argValue("--manifest");
if (!manifestPath) {
  console.error(USAGE);
  process.exit(2);
}

const concurrency = Math.max(1, intArg("--concurrency", 4));
const retries = Math.max(1, intArg("--retries", 3));
const timeoutMs = Math.max(1000, intArg("--timeout-ms", 60000));
const delayMs = intArg("--delay-ms", 300);
const minBytes = Math.max(1024, intArg("--min-bytes", 20000));
const quiet = hasFlag("--quiet");
const onlyFailed = hasFlag("--only-failed");
const validateOnly = hasFlag("--validate-only");
const downloadEnabled = hasFlag("--download");
const noStatusWrite = hasFlag("--no-status-write");
const allowWrite = hasFlag("--allow-write");
const allowNetwork = hasFlag("--allow-network");
const fallbackNoVersion = !hasFlag("--no-fallback-no-version");

if (!validateOnly && !downloadEnabled) {
  console.error("Error: refusing to download without explicit --download. Use --validate-only for local validation.");
  console.error(USAGE);
  process.exit(2);
}
if (!noStatusWrite && !allowWrite) {
  console.error("Error: status-file output requires explicit --allow-write. Use --no-status-write for a pure check.");
  process.exit(2);
}
if (downloadEnabled && (!allowWrite || !allowNetwork)) {
  console.error("Error: downloads require --download --allow-network --allow-write.");
  process.exit(2);
}

const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
const statusPath = manifestPath.replace(/_manifest\.json$/u, "_download_status.json");
const batch = path.basename(manifestPath).replace(/_manifest\.json$/u, "");
const previous = await loadPreviousStatus(statusPath);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function loadPreviousStatus(filePath) {
  try {
    const rows = JSON.parse(await fs.readFile(filePath, "utf8"));
    const byId = new Map();
    for (const row of rows) byId.set(row.arxiv_id, row);
    return byId;
  } catch {
    return new Map();
  }
}

function nowIso() {
  return new Date().toISOString();
}

function withoutVersion(pdfUrl, arxivId) {
  const id = arxivId || "";
  if (id) return `https://arxiv.org/pdf/${id}`;
  return pdfUrl.replace(/v\d+$/u, "");
}

function candidateUrls(row) {
  const urls = [row.pdf_url];
  const fallback = withoutVersion(row.pdf_url, row.arxiv_id);
  if (fallbackNoVersion && fallback && fallback !== row.pdf_url) urls.push(fallback);
  return urls;
}

async function validatePdf(filePath) {
  const stat = await fs.stat(filePath).catch(() => null);
  if (!stat) return { valid: false, reason: "missing" };
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
  return { valid: true, bytes: stat.size };
}

async function fetchWithTimeout(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      headers: { "User-Agent": "literature-research-workflow/2.0" },
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

async function downloadOnce(row, url, attempt) {
  const target = row.pdf_path;
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
    pdf_path: target,
    bytes: finalValidation.bytes,
    attempts: attempt,
    validated: true,
    error: null,
    warnings,
    updated_at: nowIso(),
  };
}

class DownloadError extends Error {
  constructor(status, message) {
    super(message);
    this.name = "DownloadError";
    this.status = status;
  }
}

async function processRow(row) {
  const target = row.pdf_path;
  const existing = await validatePdf(target);
  if (existing.valid) {
    return {
      arxiv_id: row.arxiv_id,
      status: "exists",
      pdf_url: row.pdf_url,
      final_url: row.pdf_url,
      pdf_path: target,
      bytes: existing.bytes,
      attempts: 0,
      validated: true,
      error: null,
      warnings: [],
      updated_at: nowIso(),
    };
  }

  if (validateOnly) {
    return {
      arxiv_id: row.arxiv_id,
      status: "invalid",
      pdf_url: row.pdf_url,
      final_url: null,
      pdf_path: target,
      bytes: existing.bytes ?? 0,
      attempts: 0,
      validated: false,
      error: existing.reason,
      warnings: [],
      updated_at: nowIso(),
    };
  }

  if (onlyFailed) {
    const old = previous.get(row.arxiv_id);
    const retryable = ["failed", "invalid", "download_failed", "invalid_part", "finalize_failed", "invalid_final_pdf"];
    if (old && !retryable.includes(old.status)) {
      return {
        ...old,
        status: "skipped",
        updated_at: nowIso(),
      };
    }
  }

  const urls = candidateUrls(row);
  let lastError = null;
  let lastStatus = existing.reason === "missing" ? "download_failed" : "invalid";
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
        await fs.rm(`${target}.part`, { force: true }).catch(() => {});
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
    pdf_path: target,
    bytes: existing.bytes ?? 0,
    attempts: attempt,
    validated: false,
    error: lastError || existing.reason,
    warnings: [],
    updated_at: nowIso(),
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
  await fs.writeFile(statusPath, JSON.stringify(results, null, 2), "utf8");
  statusWritten = true;
}

const counts = results.reduce((acc, item) => {
  acc[item.status] = (acc[item.status] || 0) + 1;
  return acc;
}, {});
const blockingStatuses = ["download_failed", "invalid", "invalid_part", "finalize_failed", "invalid_final_pdf"];
const failedRows = results.filter((item) => blockingStatuses.includes(item.status));
const warningCount = results.reduce((total, item) => total + (item.warnings?.length || 0), 0);
const summary = {
  batch,
  expected: results.length,
  valid_existing: counts.exists || 0,
  downloaded: counts.downloaded || 0,
  skipped: counts.skipped || 0,
  invalid: counts.invalid || 0,
  download_failed: counts.download_failed || 0,
  invalid_part: counts.invalid_part || 0,
  finalize_failed: counts.finalize_failed || 0,
  invalid_final_pdf: counts.invalid_final_pdf || 0,
  failed: failedRows.length,
  warnings: warningCount,
  status_path: statusPath,
  status_written: statusWritten,
  download_enabled: Boolean(downloadEnabled),
  validate_only: validateOnly,
};
if (failedRows.length > 0) {
  summary.failed_items = failedRows.map((item) => ({
    arxiv_id: item.arxiv_id,
    status: item.status,
    error: item.error,
  }));
}

console.log(JSON.stringify(summary));
