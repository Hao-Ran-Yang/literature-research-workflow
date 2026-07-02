from __future__ import annotations

import hashlib
import re
import urllib.parse
from dataclasses import dataclass


ARXIV_ID_RE = re.compile(r"(?i)(?P<id>\d{4}\.\d{4,5})(?:v\d+)?")
ARXIV_PREFIX_RE = re.compile(r"(?i)^arxiv[:\s]*")
ARXIV_DOI_RE = re.compile(r"(?i)^10\.48550/arxiv\.(?P<id>\d{4}\.\d{4,5})(?:v\d+)?$")
DOI_RE = re.compile(r"(?i)\b(?:doi:\s*|https?://(?:dx\.)?doi\.org/)(?P<doi>10\.\S+)")
OPENREVIEW_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
URL_RE = re.compile(r"(?i)^https?://")


@dataclass(frozen=True)
class SourceIdentity:
    source_url: str
    paper_id: str = ""
    dedup_key: str = ""
    arxiv_id: str = ""
    source_family: str = ""
    source_family_id: str = ""
    source_role: str = "resource"
    link_type: str = "resource"
    official_url: str = ""
    public_pdf_url: str = ""
    pdf_status: str = "needs_pdf_review"
    metadata_status: str = "partially_verified"
    warning: str = ""


def short_hash(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:length]


def strip_arxiv_version(value: str) -> str:
    return re.sub(r"(?i)v\d+$", "", value or "")


def normalize_arxiv_id(value: str) -> str:
    value = ARXIV_PREFIX_RE.sub("", value or "").strip()
    match = ARXIV_ID_RE.search(value)
    return strip_arxiv_version(match.group("id")) if match else ""


def normalize_doi(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"(?i)^doi:\s*", "", value)
    value = re.sub(r"(?i)^https?://(?:dx\.)?doi\.org/", "", value)
    value = value.strip().rstrip(").,;")
    return urllib.parse.unquote(value).lower()


def normalize_paper_id(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.lower().startswith("arxiv:") or ARXIV_ID_RE.fullmatch(value):
        arxiv_id = normalize_arxiv_id(value)
        return f"arxiv:{arxiv_id}" if arxiv_id else ""
    if value.lower().startswith("doi:") or re.match(r"(?i)^https?://(?:dx\.)?doi\.org/", value):
        doi = normalize_doi(value)
        arxiv = ARXIV_DOI_RE.match(doi)
        if arxiv:
            return f"arxiv:{normalize_arxiv_id(arxiv.group('id'))}"
        return f"doi:{doi}" if doi else ""
    if re.match(r"(?i)^(openreview|acl|pmlr|neurips|urlhash|pdfhash):", value):
        prefix, rest = value.split(":", 1)
        return f"{prefix.lower()}:{rest.strip()}"
    return value


def make_dedup_key(identity: SourceIdentity | dict | str) -> str:
    if isinstance(identity, SourceIdentity):
        return identity.paper_id or identity.source_url
    if isinstance(identity, dict):
        return identity.get("paper_id") or identity.get("dedup_key") or identity.get("source_url") or ""
    return normalize_paper_id(str(identity or ""))


def canonical_pdf_status(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"available", "available_remote", "imported_local", "downloaded", "already_valid"}:
        return "available"
    if normalized in {"pdf_unavailable", "unavailable", "resource_only"}:
        return "pdf_unavailable"
    return "needs_pdf_review"


def safe_filename_for_paper_id(paper_id: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", paper_id or "").strip("._")
    if not base:
        base = "paper"
    if len(base) > 96:
        base = base[:80].rstrip("._") + "_" + short_hash(paper_id, 10)
    return base


def normalize_match_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def pdf_match_keys(row: dict) -> set[str]:
    values = {
        row.get("paper_id", ""),
        row.get("source_family_id", ""),
        row.get("arxiv_id", ""),
        row.get("canonical_title", "") or row.get("title", ""),
    }
    paper_id = row.get("paper_id", "")
    if paper_id.startswith("doi:"):
        values.add(paper_id.removeprefix("doi:"))
    if paper_id.startswith("openreview:"):
        values.add(paper_id.removeprefix("openreview:"))
    if paper_id.startswith("arxiv:"):
        values.add(paper_id.removeprefix("arxiv:"))
    return {key for value in values if (key := normalize_match_key(value))}


def identity(
    *,
    source_url: str,
    paper_id: str = "",
    arxiv_id: str = "",
    source_family: str,
    source_family_id: str = "",
    source_role: str = "paper",
    link_type: str = "",
    official_url: str = "",
    public_pdf_url: str = "",
    pdf_status: str = "needs_pdf_review",
    metadata_status: str = "partially_verified",
    warning: str = "",
) -> SourceIdentity:
    normalized = normalize_paper_id(paper_id)
    return SourceIdentity(
        source_url=source_url,
        paper_id=normalized,
        dedup_key=normalized,
        arxiv_id=normalize_arxiv_id(arxiv_id),
        source_family=source_family,
        source_family_id=source_family_id,
        source_role=source_role,
        link_type=link_type or source_family,
        official_url=official_url,
        public_pdf_url=public_pdf_url,
        pdf_status=canonical_pdf_status(pdf_status),
        metadata_status=metadata_status,
        warning=warning,
    )


def derive_public_pdf_url(item: SourceIdentity | dict, evidence_links: list[str] | None = None) -> str:
    paper_id = item.paper_id if isinstance(item, SourceIdentity) else item.get("paper_id", "")
    public_pdf = item.public_pdf_url if isinstance(item, SourceIdentity) else item.get("public_pdf_url", "")
    if public_pdf:
        return public_pdf
    if paper_id.startswith("arxiv:"):
        return f"https://arxiv.org/pdf/{paper_id.removeprefix('arxiv:')}.pdf"
    if paper_id.startswith("openreview:"):
        return f"https://openreview.net/pdf?id={paper_id.removeprefix('openreview:')}"
    for link in evidence_links or []:
        if is_direct_pdf_url(link):
            return link
    return ""


def is_direct_pdf_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    return path.endswith(".pdf")


def parse_openreview(parsed: urllib.parse.ParseResult, url: str) -> SourceIdentity | None:
    if parsed.netloc.lower() != "openreview.net":
        return None
    if parsed.path.lower() not in {"/forum", "/pdf"}:
        return None
    forum_id = urllib.parse.parse_qs(parsed.query).get("id", [""])[0]
    if not forum_id or not OPENREVIEW_ID_RE.match(forum_id):
        return None
    return identity(
        source_url=url,
        paper_id=f"openreview:{forum_id}",
        source_family="openreview",
        source_family_id=forum_id,
        official_url=f"https://openreview.net/forum?id={forum_id}",
        public_pdf_url=f"https://openreview.net/pdf?id={forum_id}",
        pdf_status="available",
    )


def parse_huggingface(parsed: urllib.parse.ParseResult, url: str) -> SourceIdentity | None:
    if parsed.netloc.lower() != "huggingface.co":
        return None
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) >= 2 and parts[0] == "papers":
        arxiv_id = normalize_arxiv_id(parts[1])
        if arxiv_id:
            return identity(
                source_url=url,
                paper_id=f"arxiv:{arxiv_id}",
                arxiv_id=arxiv_id,
                source_family="huggingface_papers",
                source_family_id=arxiv_id,
                official_url=f"https://arxiv.org/abs/{arxiv_id}",
                public_pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                pdf_status="available",
            )
        return identity(
            source_url=url,
            paper_id=f"urlhash:{short_hash(url)}",
            source_family="huggingface_papers",
            source_family_id=parts[1],
            official_url=url,
            pdf_status="needs_pdf_review",
            metadata_status="needs_metadata_review",
        )
    if parts and parts[0] == "datasets":
        return identity(source_url=url, source_family="huggingface", source_role="dataset", link_type="dataset", pdf_status="pdf_unavailable")
    if parts and parts[0] == "spaces":
        return identity(source_url=url, source_family="huggingface", source_role="demo", link_type="demo", pdf_status="pdf_unavailable")
    return identity(source_url=url, source_family="huggingface", source_role="model", link_type="model", pdf_status="pdf_unavailable")


def parse_neurips(parsed: urllib.parse.ParseResult, url: str) -> SourceIdentity | None:
    host = parsed.netloc.lower()
    if host not in {"papers.neurips.cc", "neurips.cc", "www.neurips.cc"}:
        return None
    match = re.search(r"/paper(?:_files)?/paper/(?P<year>\d{4})/hash/(?P<hash>[A-Za-z0-9]+)", parsed.path)
    if match:
        year = match.group("year")
        paper_hash = match.group("hash")
        return identity(
            source_url=url,
            paper_id=f"neurips:{year}:{paper_hash}",
            source_family="neurips",
            source_family_id=f"{year}:{paper_hash}",
            official_url=url,
            pdf_status="needs_pdf_review",
        )
    return identity(
        source_url=url,
        paper_id=f"urlhash:{short_hash(url)}",
        source_family="neurips",
        source_family_id=short_hash(url),
        official_url=url,
        pdf_status="needs_pdf_review",
        metadata_status="needs_metadata_review",
        warning="neurips_url_without_stable_year_hash",
    )


def parse_source_url(value: str, *, context_text: str = "") -> SourceIdentity:
    raw = (value or "").strip().rstrip(").,;")
    if not raw:
        return identity(source_url="", source_family="unknown", source_role="resource", pdf_status="pdf_unavailable")
    doi_match = DOI_RE.search(raw)
    if doi_match or raw.lower().startswith("doi:"):
        doi = normalize_doi(doi_match.group("doi") if doi_match else raw)
        arxiv = ARXIV_DOI_RE.match(doi)
        if arxiv:
            arxiv_id = normalize_arxiv_id(arxiv.group("id"))
            return identity(
                source_url=raw,
                paper_id=f"arxiv:{arxiv_id}",
                arxiv_id=arxiv_id,
                source_family="arxiv",
                source_family_id=arxiv_id,
                official_url=f"https://arxiv.org/abs/{arxiv_id}",
                public_pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                pdf_status="available",
            )
        return identity(source_url=raw, paper_id=f"doi:{doi}", source_family="doi", source_family_id=doi, official_url=f"https://doi.org/{doi}")
    if not URL_RE.match(raw):
        arxiv_id = normalize_arxiv_id(raw)
        if arxiv_id:
            return identity(
                source_url=raw,
                paper_id=f"arxiv:{arxiv_id}",
                arxiv_id=arxiv_id,
                source_family="arxiv",
                source_family_id=arxiv_id,
                official_url=f"https://arxiv.org/abs/{arxiv_id}",
                public_pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                pdf_status="available",
            )
        return identity(source_url=raw, source_family="unknown", source_role="resource", pdf_status="pdf_unavailable", warning="unrecognized_non_url_source")

    parsed = urllib.parse.urlparse(raw)
    host = parsed.netloc.lower()
    path = parsed.path
    arxiv_id = normalize_arxiv_id(path)
    if host == "arxiv.org" and arxiv_id and re.match(r"(?i)^/(abs|pdf)/", path):
        return identity(
            source_url=raw,
            paper_id=f"arxiv:{arxiv_id}",
            arxiv_id=arxiv_id,
            source_family="arxiv",
            source_family_id=arxiv_id,
            official_url=f"https://arxiv.org/abs/{arxiv_id}",
            public_pdf_url=f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            pdf_status="available",
        )
    openreview = parse_openreview(parsed, raw)
    if openreview:
        return openreview
    huggingface = parse_huggingface(parsed, raw)
    if huggingface:
        return huggingface
    if host == "aclanthology.org":
        anthology_id = path.strip("/").removesuffix(".pdf")
        link_type = "official_pdf" if is_direct_pdf_url(raw) else "acl"
        return identity(source_url=raw, paper_id=f"acl:{anthology_id}", source_family="acl", source_family_id=anthology_id, official_url=f"https://aclanthology.org/{anthology_id}/", public_pdf_url=raw if link_type == "official_pdf" else "", pdf_status="available" if link_type == "official_pdf" else "needs_pdf_review", link_type=link_type)
    if host == "proceedings.mlr.press":
        pmlr_id = path.strip("/").removesuffix(".html").removesuffix(".pdf").replace("/", ":")
        link_type = "official_pdf" if is_direct_pdf_url(raw) else "pmlr"
        return identity(source_url=raw, paper_id=f"pmlr:{pmlr_id}", source_family="pmlr", source_family_id=pmlr_id, official_url=raw, public_pdf_url=raw if link_type == "official_pdf" else "", pdf_status="available" if link_type == "official_pdf" else "needs_pdf_review", link_type=link_type)
    neurips = parse_neurips(parsed, raw)
    if neurips:
        return neurips
    if is_direct_pdf_url(raw):
        return identity(source_url=raw, paper_id=f"urlhash:{short_hash(raw)}", source_family="pdf", source_family_id=short_hash(raw), official_url=raw, public_pdf_url=raw, pdf_status="available", link_type="official_pdf")
    if "github.com" in host:
        return identity(source_url=raw, source_family="github", source_role="code", link_type="code", pdf_status="pdf_unavailable")
    return identity(
        source_url=raw,
        paper_id=f"urlhash:{short_hash(raw)}",
        source_family="url",
        source_family_id=short_hash(raw),
        source_role="project",
        link_type="project",
        official_url=raw,
        pdf_status="needs_pdf_review",
        metadata_status="needs_metadata_review",
    )


def classify_source_link(url: str, *, context_text: str = "") -> SourceIdentity:
    return parse_source_url(url, context_text=context_text)
