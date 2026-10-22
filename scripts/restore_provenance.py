#!/usr/bin/env python3
"""Restore ``source_id`` provenance for staging documents, by evidence only.

Background: old ``download_html.py`` runs wrote no ``source_id`` into
``data/inbox/<sha16>/meta.json``.  Ingestion then fell back to the inbox
directory name (a sha256 prefix) as the document's source_id, so those rows
carry a 16-hex-char pseudo-source and land in ``source_trust='unknown'``.

This script repairs that *without guessing*.  For every staging document whose
recorded source_id is missing or looks like a sha256 prefix it looks for the
inbox directory that produced it and resolves a source in this order:

  a. meta ............ ``meta.json["source_id"]`` (authoritative if present)
  b. data_items_url .. ``data_items.url`` equals a URL recorded for the inbox
                       entry (``meta.url`` / ``meta.final_url``) or for the
                       document (``metadata.final_url`` / ``requested_url``)
  b. data_items_sha .. ``data_items.sha256`` equals the file sha
                       (``meta.sha256`` or the version's ``content_hash``)
  c. host_map ........ the URL host maps to exactly one source_id across all
                       ``data_items`` rows

Every route must yield exactly one source_id.  If two routes disagree, if an
inbox directory matches more than one distinct provenance signature, or if the
host is shared by several sources, the document is left untouched and reported
as unresolved with the competing evidence.

Dry-run by default.  ``--apply`` writes only
``metadata || {source_id, provenance_restored, provenance_evidence}``, then
re-runs ``scripts/assess_eligibility.py --apply`` so source_trust / licence /
index_eligibility follow the restored source.  It never touches
``domain_review_status`` or ``verification_status``.  An audit file is written
to ``data/reports/provenance_restore_<ts>.json``.

Usage (from apps/api, like the other scripts):
    uv run python ../../scripts/restore_provenance.py
    uv run python ../../scripts/restore_provenance.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

INBOX = ROOT / "data" / "inbox"
REPORTS = ROOT / "data" / "reports"
SHA16 = re.compile(r"^[0-9a-f]{16}$")

ROUTES = ("meta", "data_items_url", "data_items_sha", "host_map")


def norm_url(value: str | None) -> str | None:
    """Case-normalise scheme/host, drop the fragment, keep query and path.

    Query strings matter here (``enaca.org/?id=1092``), so they are preserved.
    Matching is otherwise exact: a normalised URL is treated as the same
    resource, never as a fuzzy/prefix match.
    """
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if not parts.scheme or not parts.netloc:
        return None
    path = parts.path.rstrip("/") or "/"
    out = f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}"
    if parts.query:
        out += f"?{parts.query}"
    return out


def host_of(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    return parts.netloc.lower() or None


def as_str(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def is_orphan_meta(metadata: dict) -> bool:
    """True when the recorded source_id cannot be a real whitelist id.

    Real source ids in this corpus are human-readable slugs
    (``nftec-ybfk``, ``worldfish-dspace``, ``ffrc-jstg``).  The broken ingest
    path wrote exactly the 16-hex-char sha256 prefix.
    """
    sid = as_str(metadata.get("source_id"))
    return sid is None or bool(SHA16.match(sid))


def load_inbox() -> tuple[list[dict], dict, dict, dict, dict]:
    """Read every ``data/inbox/*/meta.json`` once and index it five ways."""
    entries: list[dict] = []
    by_sha: dict[str, list[int]] = defaultdict(list)
    by_sha16: dict[str, list[int]] = defaultdict(list)
    by_url: dict[str, list[int]] = defaultdict(list)
    by_doc_id: dict[str, list[int]] = defaultdict(list)

    if not INBOX.is_dir():
        return entries, by_sha, by_sha16, by_url, by_doc_id

    for directory in sorted(INBOX.iterdir()):
        if not directory.is_dir():
            continue
        meta_path = directory / "meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        sha = as_str(meta.get("sha256"))
        urls = {
            u
            for u in (norm_url(as_str(meta.get("url"))), norm_url(as_str(meta.get("final_url"))))
            if u
        }
        ingest = meta.get("ingest") if isinstance(meta.get("ingest"), dict) else {}
        doc_id = as_str(ingest.get("document_id"))
        idx = len(entries)
        entries.append(
            {
                "dir": directory.name,
                "meta": meta,
                "sha256": sha,
                "urls": sorted(urls),
                "document_id": doc_id,
            }
        )
        if sha:
            by_sha[sha].append(idx)
            by_sha16[sha[:16]].append(idx)
        for u in urls:
            by_url[u].append(idx)
        if doc_id:
            by_doc_id[doc_id].append(idx)

    return entries, by_sha, by_sha16, by_url, by_doc_id


def pick_inbox_dir(
    doc_id: str,
    content_hash: str | None,
    doc_urls: set[str],
    entries: list[dict],
    by_sha: dict,
    by_sha16: dict,
    by_url: dict,
    by_doc_id: dict,
) -> tuple[dict | None, str, str]:
    """Return (entry, status, detail) where status is ok / none / ambiguous.

    A directory is a candidate if *any* of these holds:
      * ``meta.ingest.document_id`` is this document,
      * its sha256 (or the sha256-prefixed directory name) is the version hash,
      * one of its recorded URLs is a URL recorded on the document.

    More than one *distinct provenance signature* (sha256 + url set) means we
    cannot say which download produced this document, so we refuse.
    """
    candidates: set[int] = set()
    if doc_id in by_doc_id:
        candidates.update(by_doc_id[doc_id])
    if content_hash:
        candidates.update(by_sha.get(content_hash, []))
        candidates.update(by_sha16.get(content_hash[:16], []))
    for u in doc_urls:
        candidates.update(by_url.get(u, []))

    if not candidates:
        return None, "none", "no inbox dir matched by document_id, sha256 or url"

    signatures: dict[tuple, list[int]] = defaultdict(list)
    for i in sorted(candidates):
        e = entries[i]
        signatures[(e["sha256"], tuple(e["urls"]))].append(i)

    if len(signatures) > 1:
        detail = "; ".join(
            f"sha256={(sig[0] or 'none')[:16]} urls={','.join(sig[1]) or 'none'} "
            f"dirs={','.join(entries[i]['dir'] for i in idxs)}"
            for sig, idxs in signatures.items()
        )
        return None, "ambiguous", f"{len(signatures)} distinct inbox signatures: {detail}"

    idxs = next(iter(signatures.values()))
    # Prefer the directory whose *name* is the content hash, else the lowest name.
    chosen = min(
        idxs,
        key=lambda i: (
            0 if content_hash and entries[i]["dir"] == content_hash[:16] else 1,
            entries[i]["dir"],
        ),
    )
    detail = f"inbox/{entries[chosen]['dir']}"
    if len(idxs) > 1:
        detail += f" (duplicate dirs: {','.join(entries[i]['dir'] for i in idxs)})"
    return entries[chosen], "ok", detail


async def run(apply: bool) -> int:
    from sqlalchemy import text
    from app.db import SessionLocal, init_db

    entries, by_sha, by_sha16, by_url, by_doc_id = load_inbox()
    print(f"inbox entries: {len(entries)}")

    await init_db()
    async with SessionLocal() as db:
        item_rows = (
            await db.execute(
                text(
                    "SELECT id, source_id, url, final_url, sha256, document_id "
                    "FROM data_items"
                )
            )
        ).all()
        doc_rows = (
            await db.execute(
                text(
                    "SELECT d.id, d.metadata, v.content_hash, d.title "
                    "FROM kb_documents d "
                    "LEFT JOIN kb_document_versions v ON v.id = d.current_version_id "
                    "WHERE d.status = 'staging'"
                )
            )
        ).all()

        before_elig = dict(
            (
                await db.execute(
                    text(
                        "SELECT coalesce(index_eligibility,'(null)'), count(*) "
                        "FROM kb_documents WHERE status='staging' "
                        "GROUP BY 1"
                    )
                )
            ).all()
        )

        # ---- evidence indexes over data_items -------------------------------
        url_sids: dict[str, set[str]] = defaultdict(set)
        url_items: dict[str, set[str]] = defaultdict(set)
        sha_sids: dict[str, set[str]] = defaultdict(set)
        sha_items: dict[str, set[str]] = defaultdict(set)
        host_sids: dict[str, set[str]] = defaultdict(set)
        link_sids: dict[str, set[str]] = defaultdict(set)

        for item_id, sid, url, final_url, sha, linked_doc in item_rows:
            sid = as_str(sid)
            for raw in (url, final_url):
                u = norm_url(raw)
                if not u:
                    continue
                h = host_of(raw)
                if h and sid:
                    host_sids[h].add(sid)
                if not sid:
                    continue
                url_sids[u].add(sid)
                url_items[u].add(str(item_id))
            if not sid:
                continue
            if sha:
                sha_sids[sha].add(sid)
                sha_items[sha].add(str(item_id))
            if linked_doc:
                link_sids[str(linked_doc)].add(sid)

        # host -> single source only when every data_items row agrees.
        host_unique = {h: next(iter(s)) for h, s in host_sids.items() if len(s) == 1}

        # ---- resolve --------------------------------------------------------
        results: list[dict] = []
        unresolved: list[dict] = []
        route_counts: Counter[str] = Counter()

        for doc_id, metadata, content_hash, title in doc_rows:
            metadata = metadata or {}
            if not is_orphan_meta(metadata):
                continue

            doc_id = str(doc_id)
            doc_urls = {
                u
                for u in (
                    norm_url(as_str(metadata.get("final_url"))),
                    norm_url(as_str(metadata.get("requested_url"))),
                )
                if u
            }

            entry, inbox_status, inbox_detail = pick_inbox_dir(
                doc_id, content_hash, doc_urls, entries, by_sha, by_sha16, by_url, by_doc_id
            )
            meta = entry["meta"] if entry else {}
            meta_urls = set(entry["urls"]) if entry else set()
            all_urls = sorted(doc_urls | meta_urls)
            file_sha = as_str(meta.get("sha256")) or content_hash

            if inbox_status == "ambiguous":
                unresolved.append(
                    {
                        "doc_id": doc_id,
                        "title": title,
                        "reason": "ambiguous inbox directory match",
                        "detail": inbox_detail,
                        "current_source_id": metadata.get("source_id"),
                    }
                )
                route_counts["unresolved"] += 1
                continue

            found: dict[str, tuple[str, str]] = {}  # route -> (sid, evidence)
            conflicts: list[str] = []

            # (a) explicit source_id in meta.json
            meta_sid = as_str(meta.get("source_id"))
            if meta_sid:
                found["meta"] = (meta_sid, f"{inbox_detail}/meta.json source_id={meta_sid}")

            # (b1) data_items.url / final_url == a recorded URL
            url_hit_sids: set[str] = set()
            url_hit_evidence: list[str] = []
            for u in all_urls:
                sids = url_sids.get(u)
                if not sids:
                    continue
                url_hit_sids |= sids
                url_hit_evidence.append(
                    f"url={u} data_items={','.join(sorted(url_items[u]))}"
                )
            if len(url_hit_sids) == 1:
                found["data_items_url"] = (next(iter(url_hit_sids)), url_hit_evidence[0])
            elif len(url_hit_sids) > 1:
                conflicts.append(
                    "url evidence disagrees: "
                    + " | ".join(url_hit_evidence)
                    + " -> sids="
                    + ",".join(sorted(url_hit_sids))
                )

            # (b2) data_items.sha256 == file sha
            if file_sha:
                sids = sha_sids.get(file_sha)
                if sids:
                    if len(sids) == 1:
                        found["data_items_sha"] = (
                            next(iter(sids)),
                            f"sha256={file_sha} data_items={','.join(sorted(sha_items[file_sha]))}",
                        )
                    else:
                        conflicts.append(
                            f"sha256={file_sha} matches several sources: {','.join(sorted(sids))}"
                        )

            # (c) host map, only if the host is unambiguous across data_items
            host_hit = None
            for u in all_urls:
                h = host_of(u)
                if h and h in host_unique:
                    host_hit = (host_unique[h], h)
                    break

            # ---- decide -----------------------------------------------------
            chosen_route, chosen_sid, chosen_evidence = None, None, None
            for route in ROUTES:
                if route in found:
                    chosen_route, (chosen_sid, chosen_evidence) = route, found[route]
                    break

            direct_sids = {sid for sid, _ in found.values()}
            if len(direct_sids) > 1:
                conflicts.append(
                    "routes disagree: "
                    + "; ".join(f"{r}->{s}" for r, (s, _) in sorted(found.items()))
                )
            if conflicts:
                unresolved.append(
                    {
                        "doc_id": doc_id,
                        "title": title,
                        "reason": "conflicting evidence",
                        "detail": " | ".join(conflicts),
                        "current_source_id": metadata.get("source_id"),
                    }
                )
                route_counts["unresolved"] += 1
                continue

            if chosen_route is None and host_hit:
                sid, h = host_hit
                chosen_route = "host_map"
                chosen_sid = sid
                chosen_evidence = (
                    f"host={h} -> {sid} (only source_id for this host in data_items; "
                    f"{sum(1 for r in item_rows if host_of(r[2]) == h)} rows)"
                )

            if chosen_route is None:
                unresolved.append(
                    {
                        "doc_id": doc_id,
                        "title": title,
                        "reason": "no unambiguous evidence",
                        "detail": (
                            f"urls={all_urls or 'none'} sha256={file_sha or 'none'} "
                            f"hosts={sorted({host_of(u) for u in all_urls if host_of(u)})}"
                        ),
                        "current_source_id": metadata.get("source_id"),
                    }
                )
                route_counts["unresolved"] += 1
                continue

            # A linked data_items row must agree with the resolved source.
            linked = link_sids.get(doc_id, set())
            if linked and chosen_sid not in linked:
                unresolved.append(
                    {
                        "doc_id": doc_id,
                        "title": title,
                        "reason": "linked data_items disagrees",
                        "detail": (
                            f"resolved {chosen_sid} via {chosen_route} "
                            f"({chosen_evidence}) but data_items.document_id rows say "
                            f"{','.join(sorted(linked))}"
                        ),
                        "current_source_id": metadata.get("source_id"),
                    }
                )
                route_counts["unresolved"] += 1
                continue

            route_counts[chosen_route] += 1
            results.append(
                {
                    "doc_id": doc_id,
                    "title": title,
                    "source_id": chosen_sid,
                    "route": chosen_route,
                    "evidence": chosen_evidence,
                    "inbox": inbox_detail,
                    "previous_source_id": metadata.get("source_id"),
                }
            )

        # ---- report ---------------------------------------------------------
        print("resolution routes:")
        for route in (*ROUTES, "unresolved"):
            print(f"  {route:16s} {route_counts.get(route, 0)}")
        print(f"  {'candidates':16s} {len(results)}")

        if unresolved:
            print(f"\nrefused ({len(unresolved)}):")
            for row in unresolved[:20]:
                print(f"  {row['doc_id']}  {row['reason']}: {row['detail'][:200]}")
            if len(unresolved) > 20:
                print(f"  ... {len(unresolved) - 20} more in audit file")

        if not apply:
            print("\ndry-run: no rows written; pass --apply to restore provenance")
            return 0

        # ---- apply ----------------------------------------------------------
        for row in results:
            await db.execute(
                text(
                    "UPDATE kb_documents "
                    "SET metadata = metadata || jsonb_build_object("
                    "  'source_id', CAST(:sid AS text),"
                    "  'provenance_restored', CAST(:route AS text),"
                    "  'provenance_evidence', CAST(:evidence AS text)"
                    ") "
                    "WHERE id = :doc_id"
                ),
                {
                    "sid": row["source_id"],
                    "route": row["route"],
                    "evidence": row["evidence"],
                    "doc_id": row["doc_id"],
                },
            )
        await db.commit()

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        REPORTS.mkdir(parents=True, exist_ok=True)
        out = REPORTS / f"provenance_restore_{stamp}.json"
        out.write_text(
            json.dumps(
                {
                    "at": stamp,
                    "applied": True,
                    "routes": {r: route_counts.get(r, 0) for r in (*ROUTES, "unresolved")},
                    "resolved": len(results),
                    "unresolved_count": len(unresolved),
                    "documents": results,
                    "unresolved": unresolved,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nupdated {len(results)} documents")
        print(f"wrote {out}")

    # ---- re-run eligibility with a *fresh* session --------------------------
    print("\nre-running assess_eligibility.py --apply ...")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "assess_eligibility.py"), "--apply"],
        cwd=str(ROOT / "apps" / "api"),
        capture_output=True,
        text=True,
    )
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        print(f"assess_eligibility failed with exit {proc.returncode}", file=sys.stderr)
        return proc.returncode

    async with SessionLocal() as db:
        after_elig = dict(
            (
                await db.execute(
                    text(
                        "SELECT coalesce(index_eligibility,'(null)'), count(*) "
                        "FROM kb_documents WHERE status='staging' "
                        "GROUP BY 1"
                    )
                )
            ).all()
        )
    print("\nstaging index_eligibility before -> after:")
    for key in sorted(set(before_elig) | set(after_elig)):
        print(f"  {key:16s} {before_elig.get(key, 0):4d} -> {after_elig.get(key, 0):4d}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--apply",
        action="store_true",
        help="write metadata and re-run eligibility (default: dry-run)",
    )
    args = ap.parse_args()
    return asyncio.run(run(args.apply))


if __name__ == "__main__":
    raise SystemExit(main())