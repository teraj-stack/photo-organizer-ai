#!/usr/bin/env python3
"""Backend aplikacji Photo Organizer AI (FastAPI) — szybki, nieblokujący."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from PIL import Image, ImageOps
from pydantic import BaseModel

Image.MAX_IMAGE_PIXELS = None  # Obsługa dużych renderów 2K/4K/8K bez ostrzeżeń

APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR / "static"
UNDO_LOG_PATH = APP_DIR / "undo_log.json"

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".avif", ".heic",
}

SKIP_FILES = {".DS_Store", "Thumbs.db", "Icon\r"}

SKIP_DIR_NAMES = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".Trash",
    "Library", "Applications",
    "_KWARANTANNA_DUPLIKATOW", "_POSORTOWANE_AI",
}

SKIP_DIR_SUFFIXES = (
    ".photoslibrary", ".photolibrary", ".app", ".framework",
    ".bundle", ".xcodeproj", ".xcworkspace", ".playground", ".swiftpm",
)

DEFAULT_CATEGORIES = [
    {
        "id": "frontend_telefon",
        "label": "Frontend telefonu (Mobile UI)",
        "description": "Zrzuty ekranu aplikacji mobilnych, makiety UI na smartfon, pionowe widoki interfejsu telefonu",
    },
    {
        "id": "frontend_strona",
        "label": "Frontend strony WWW (Desktop UI)",
        "description": "Zrzuty ekranu stron internetowych, landing page, panele webowe, makiety desktopowe",
    },
    {
        "id": "wizualizacja_kliniki",
        "label": "Wizualizacja / projekt kliniki",
        "description": "Wizualizacje 3D, rzuty, wnętrza gabinetów, budynki, architektura i aranżacja kliniki",
    },
    {
        "id": "zdjecia_inne",
        "label": "Inne zdjęcia i grafiki",
        "description": "Zdjęcia prywatne, ikony, losowe obrazy, dokumenty lub grafiki niepasujące do powyższych",
    },
]

app = FastAPI(title="Photo Organizer AI")


# ---------------------------------------------------------------------------
# Pomocnicze funkcje
# ---------------------------------------------------------------------------

def iter_files(folders: list[str], images_only: bool = False, max_files: int = 50000) -> list[Path]:
    results: list[Path] = []
    seen_roots: set[Path] = set()
    for raw in folders:
        root = Path(raw).expanduser().resolve()
        if not root.exists() or not root.is_dir() or root in seen_roots:
            continue
        seen_roots.add(root)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".")
                and d not in SKIP_DIR_NAMES
                and not d.lower().endswith(SKIP_DIR_SUFFIXES)
            ]
            for fname in filenames:
                if fname in SKIP_FILES or fname.startswith("._"):
                    continue
                p = Path(dirpath) / fname
                if p.is_symlink():
                    continue
                if images_only and p.suffix.lower() not in IMAGE_EXTS:
                    continue
                results.append(p)
                if len(results) >= max_files:
                    return results
    return results


def partial_hash(path: Path, chunk_size: int = 65536) -> str | None:
    try:
        size = path.stat().st_size
        h = hashlib.sha256()
        with path.open("rb") as f:
            h.update(f.read(chunk_size))
            if size > chunk_size:
                f.seek(max(0, size - chunk_size))
                h.update(f.read(chunk_size))
        return h.hexdigest()
    except OSError:
        return None


def sha256_file(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            while chunk := f.read(1024 * 1024):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def compute_dhash(path: Path, hash_size: int = 8) -> int | None:
    try:
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img).convert("L").resize(
                (hash_size + 1, hash_size), Image.Resampling.LANCZOS
            )
            pixels = list(img.getdata())
            diff = 0
            for row in range(hash_size):
                offset = row * (hash_size + 1)
                for col in range(hash_size):
                    diff = (diff << 1) | (1 if pixels[offset + col] > pixels[offset + col + 1] else 0)
            return diff
    except Exception:
        return None


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def make_thumbnail_b64(path: Path, max_side: int = 512) -> tuple[str, int, int]:
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        w, h = img.size
        img = img.convert("RGB")
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return base64.b64encode(buf.getvalue()).decode("ascii"), w, h


def heuristic_classify(path: Path, width: int, height: int) -> dict[str, Any]:
    low = str(path).lower()
    ratio = width / max(height, 1)

    if any(k in low for k in ("klinik", "clinic", "gabinet", "wnetrz", "wnętrz", "budynk", "architek", "render", "roślin", "roslin")):
        return {
            "category": "wizualizacja_kliniki",
            "confidence": 0.78,
            "reason": "Ścieżka/nazwa wskazuje na projekt lub wizualizację kliniki.",
            "engine": "heurystyka",
        }
    if any(k in low for k in ("mobile", "ios", "android", "iphone", "telefon", "phone", "app_ui")) or (ratio < 0.62 and height >= 800):
        return {
            "category": "frontend_telefon",
            "confidence": 0.72,
            "reason": f"Pionowe proporcje ({width}x{height}) lub nazwa sugerują widok mobilny.",
            "engine": "heurystyka",
        }
    if any(k in low for k in ("web", "strona", "landing", "desktop", "zrzut ekranu", "screenshot", "pulpit", "dashboard", "frontend")):
        return {
            "category": "frontend_strona",
            "confidence": 0.74,
            "reason": f"Nazwa/ścieżka ({width}x{height}) sugeruje zrzut ekranu lub frontend strony WWW.",
            "engine": "heurystyka",
        }
    return {
        "category": "zdjecia_inne",
        "confidence": 0.50,
        "reason": f"Brak jednoznacznych słów kluczowych ({width}x{height}) — użyj trybu AI (Gemini lub Ollama).",
        "engine": "heurystyka",
    }


def build_classification_prompt(categories: list[dict[str, str]], width: int, height: int, filename: str) -> str:
    cat_lines = "\n".join(
        f'- "{c["id"]}": {c["label"]} — {c["description"]}' for c in categories
    )
    return (
        "Jesteś precyzyjnym asystentem klasyfikującym obrazy i projekty graficzne.\n"
        f"Nazwa pliku: {filename}\n"
        f"Wymiary: {width}x{height} px\n\n"
        "Wybierz DOKŁADNIE JEDNĄ kategorię z poniższej listy:\n"
        f"{cat_lines}\n\n"
        "Zwróć wyłącznie poprawny JSON bez markdownu, w formacie:\n"
        '{"category": "<id_kategorii>", "confidence": 0.92, "reason": "krótkie uzasadnienie po polsku (max 1 zdanie)"}'
    )


def parse_json_response(text: str, valid_ids: set[str]) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1:
        cleaned = cleaned[start : end + 1]
    data = json.loads(cleaned)
    cat = data.get("category", "zdjecia_inne")
    if cat not in valid_ids:
        cat = next(iter(valid_ids))
    conf = max(0.0, min(1.0, float(data.get("confidence", 0.7))))
    reason = str(data.get("reason", ""))[:220]
    return {"category": cat, "confidence": round(conf, 2), "reason": reason}


async def classify_with_gemini(
    path: Path, categories: list[dict[str, str]], api_key: str, model: str = "gemini-2.5-flash"
) -> dict[str, Any]:
    b64, w, h = await asyncio.to_thread(make_thumbnail_b64, path)
    prompt = build_classification_prompt(categories, w, h, path.name)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                ]
            }
        ],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        body = resp.json()
    text = body["candidates"][0]["content"]["parts"][0]["text"]
    parsed = parse_json_response(text, {c["id"] for c in categories})
    parsed["engine"] = f"gemini:{model}"
    return parsed


async def classify_with_ollama(
    path: Path, categories: list[dict[str, str]], ollama_url: str = "http://127.0.0.1:11434", model: str = "qwen2.5vl:7b"
) -> dict[str, Any]:
    b64, w, h = await asyncio.to_thread(make_thumbnail_b64, path)
    prompt = build_classification_prompt(categories, w, h, path.name)
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [b64],
        "stream": False,
        "format": "json",
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(f"{ollama_url.rstrip('/')}/api/generate", json=payload)
        resp.raise_for_status()
        body = resp.json()
    text = body.get("response", "{}")
    parsed = parse_json_response(text, {c["id"] for c in categories})
    parsed["engine"] = f"ollama:{model}"
    return parsed


def append_undo_entries(entries: list[dict[str, str]]) -> None:
    existing = []
    if UNDO_LOG_PATH.exists():
        try:
            existing = json.loads(UNDO_LOG_PATH.read_text())
        except Exception:
            existing = []
    existing.append({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "moves": entries,
    })
    UNDO_LOG_PATH.write_text(json.dumps(existing, indent=2, ensure_ascii=False))


def safe_move(src: Path, dst_dir: Path) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    target = dst_dir / src.name
    if target.exists():
        stem = src.stem
        suffix = src.suffix
        i = 1
        while target.exists():
            target = dst_dir / f"{stem}__{i}{suffix}"
            i += 1
    shutil.move(str(src), str(target))
    return target


def _scan_duplicates_sync(req: DuplicateScanRequest) -> dict[str, Any]:
    files = iter_files(req.folders, images_only=not req.include_all_files, max_files=req.max_files)
    by_size: dict[int, list[Path]] = defaultdict(list)
    for p in files:
        try:
            st = p.stat()
            if st.st_size > 0:
                by_size[st.st_size].append(p)
        except OSError:
            continue

    by_partial: dict[tuple[int, str], list[Path]] = defaultdict(list)
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        for p in paths:
            ph = partial_hash(p)
            if ph:
                by_partial[(size, ph)].append(p)

    exact_groups: list[dict[str, Any]] = []
    seen_exact: set[str] = set()
    for (size, _), paths in by_partial.items():
        if len(paths) < 2:
            continue
        by_hash: dict[str, list[Path]] = defaultdict(list)
        for p in paths:
            fh = sha256_file(p)
            if fh:
                by_hash[fh].append(p)
        for fh, gpaths in by_hash.items():
            if len(gpaths) < 2:
                continue
            sp = sorted(str(x) for x in gpaths)
            seen_exact.update(sp[1:])
            is_img = Path(sp[0]).suffix.lower() in IMAGE_EXTS
            exact_groups.append({
                "type": "exact",
                "is_image": is_img,
                "size_bytes": size,
                "reclaimable_bytes": size * (len(sp) - 1),
                "keep": sp[0],
                "duplicates": sp[1:],
                "all_paths": sp,
            })

    exact_groups.sort(key=lambda g: g["reclaimable_bytes"], reverse=True)

    similar_groups: list[dict[str, Any]] = []
    if req.find_similar:
        unique_imgs = [
            p for p in files
            if p.suffix.lower() in IMAGE_EXTS and str(p) not in seen_exact
        ][:600]
        hashes: list[tuple[Path, int]] = []
        for p in unique_imgs:
            dh = compute_dhash(p)
            if dh is not None:
                hashes.append((p, dh))
        visited = [False] * len(hashes)
        for i in range(len(hashes)):
            if visited[i]:
                continue
            p_i, h_i = hashes[i]
            cluster = [p_i]
            for j in range(i + 1, len(hashes)):
                if visited[j]:
                    continue
                p_j, h_j = hashes[j]
                if hamming_distance(h_i, h_j) <= req.similarity_threshold:
                    visited[j] = True
                    cluster.append(p_j)
            if len(cluster) > 1:
                visited[i] = True
                cluster.sort(key=lambda x: x.stat().st_size if x.exists() else 0, reverse=True)
                sp = [str(x) for x in cluster]
                reclaim = sum(x.stat().st_size for x in cluster[1:] if x.exists())
                similar_groups.append({
                    "type": "similar",
                    "is_image": True,
                    "size_bytes": cluster[0].stat().st_size if cluster[0].exists() else 0,
                    "reclaimable_bytes": reclaim,
                    "keep": sp[0],
                    "duplicates": sp[1:],
                    "all_paths": sp,
                })
        similar_groups.sort(key=lambda g: g["reclaimable_bytes"], reverse=True)

    all_exact_dups = [p for g in exact_groups for p in g["duplicates"]]

    return {
        "scanned_files": len(files),
        "exact_groups_count": len(exact_groups),
        "exact_extra_files_count": len(all_exact_dups),
        "exact_reclaimable_bytes": sum(g["reclaimable_bytes"] for g in exact_groups),
        "similar_groups_count": len(similar_groups),
        "similar_reclaimable_bytes": sum(g["reclaimable_bytes"] for g in similar_groups),
        "exact_groups": exact_groups[:150],
        "all_exact_duplicate_paths": all_exact_dups,
        "similar_groups": similar_groups[:80],
    }


def _quarantine_sync(files: list[str], quarantine_dir: str) -> dict[str, Any]:
    qdir = Path(quarantine_dir).expanduser().resolve()
    moved = []
    errors = []
    for raw in files:
        src = Path(raw).expanduser().resolve()
        if not src.exists():
            continue
        try:
            dst = safe_move(src, qdir)
            moved.append({"from": str(src), "to": str(dst)})
        except Exception as exc:
            errors.append({"file": str(src), "error": str(exc)})
    if moved:
        append_undo_entries(moved)
    return {"moved_count": len(moved), "quarantine_dir": str(qdir), "errors": errors}


# ---------------------------------------------------------------------------
# Modele zapytań API
# ---------------------------------------------------------------------------

class DuplicateScanRequest(BaseModel):
    folders: list[str]
    include_all_files: bool = True
    find_similar: bool = False
    similarity_threshold: int = 6
    max_files: int = 50000


class QuarantineRequest(BaseModel):
    files: list[str]
    quarantine_dir: str = str(Path.home() / "Desktop" / "_KWARANTANNA_DUPLIKATOW")


class FolderActionRequest(BaseModel):
    folder: str


class ClassifyRequest(BaseModel):
    folders: list[str]
    engine: str = "heuristic"
    api_key: str = ""
    model: str = ""
    ollama_url: str = "http://127.0.0.1:11434"
    limit: int = 40
    categories: list[dict[str, str]] = DEFAULT_CATEGORIES


class MoveItem(BaseModel):
    source: str
    category: str


class OrganizeRequest(BaseModel):
    items: list[MoveItem]
    target_root: str = str(Path.home() / "Pictures" / "_POSORTOWANE_AI")
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Endpointy
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@app.get("/api/defaults")
def get_defaults() -> dict[str, Any]:
    home = Path.home()
    qdir = home / "Desktop" / "_KWARANTANNA_DUPLIKATOW"
    q_count = 0
    q_bytes = 0
    if qdir.exists():
        for f in qdir.iterdir():
            if f.is_file() and f.name not in SKIP_FILES:
                q_count += 1
                try:
                    q_bytes += f.stat().st_size
                except OSError:
                    pass
    return {
        "folders": [
            str(home / "Pictures"),
            str(home / "Desktop"),
            str(home / "Documents"),
            str(home / "Downloads"),
        ],
        "categories": DEFAULT_CATEGORIES,
        "quarantine_dir": str(qdir),
        "quarantine_count": q_count,
        "quarantine_bytes": q_bytes,
        "target_root": str(home / "Pictures" / "_POSORTOWANE_AI"),
        "has_env_gemini_key": bool(os.environ.get("GEMINI_API_KEY")),
    }


@app.get("/api/thumb")
async def get_thumb(path: str = Query(...)) -> Response:
    p = Path(path).expanduser().resolve()
    if not p.exists() or not p.is_file() or p.suffix.lower() not in IMAGE_EXTS:
        raise HTTPException(status_code=404, detail="Brak podglądu")

    def _make():
        with Image.open(p) as img:
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((280, 280), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75)
            return buf.getvalue()

    try:
        data = await asyncio.to_thread(_make)
        return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "max-age=300"})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/duplicates/scan")
async def scan_duplicates(req: DuplicateScanRequest) -> dict[str, Any]:
    return await asyncio.to_thread(_scan_duplicates_sync, req)


@app.post("/api/duplicates/quarantine")
async def quarantine_duplicates(req: QuarantineRequest) -> dict[str, Any]:
    return await asyncio.to_thread(_quarantine_sync, req.files, req.quarantine_dir)


@app.post("/api/open-folder")
def open_folder(req: FolderActionRequest) -> dict[str, Any]:
    p = Path(req.folder).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(["open", str(p)])
    return {"opened": str(p)}


@app.post("/api/quarantine/trash")
async def trash_quarantine(req: FolderActionRequest) -> dict[str, Any]:
    """Przenosi zawartość folderu kwarantanny do Kosza macOS (~/.Trash)."""
    qdir = Path(req.folder).expanduser().resolve()
    trash_dir = Path.home() / ".Trash"
    if not qdir.exists():
        return {"trashed_count": 0}

    def _move_to_trash():
        count = 0
        for item in list(qdir.iterdir()):
            if item.name in SKIP_FILES:
                continue
            try:
                safe_move(item, trash_dir)
                count += 1
            except Exception:
                pass
        return count

    count = await asyncio.to_thread(_move_to_trash)
    return {"trashed_count": count, "trash_dir": str(trash_dir)}


@app.post("/api/classify")
async def classify_images(req: ClassifyRequest) -> dict[str, Any]:
    effective_limit = 50000 if req.limit <= 0 else req.limit
    images = await asyncio.to_thread(iter_files, req.folders, True, effective_limit)
    api_key = req.api_key.strip() or os.environ.get("GEMINI_API_KEY", "")
    results = []

    for p in images:
        try:
            def _dims(path=p):
                with Image.open(path) as img:
                    img = ImageOps.exif_transpose(img)
                    return img.size, path.stat().st_size
            (w, h), size_bytes = await asyncio.to_thread(_dims)
        except Exception:
            continue

        try:
            if req.engine == "gemini":
                if not api_key:
                    raise HTTPException(status_code=400, detail="Podaj klucz GEMINI_API_KEY dla trybu Gemini.")
                pred = await classify_with_gemini(
                    p, req.categories, api_key=api_key, model=req.model or "gemini-2.5-flash"
                )
            elif req.engine == "ollama":
                pred = await classify_with_ollama(
                    p, req.categories, ollama_url=req.ollama_url, model=req.model or "qwen2.5vl:7b"
                )
            else:
                pred = heuristic_classify(p, w, h)
        except HTTPException:
            raise
        except Exception as exc:
            pred = heuristic_classify(p, w, h)
            pred["reason"] = f"Fallback (błąd AI: {exc}) — {pred['reason']}"

        results.append({
            "path": str(p),
            "name": p.name,
            "width": w,
            "height": h,
            "size_bytes": size_bytes,
            **pred,
        })

    return {"count": len(results), "items": results}


@app.post("/api/organize/apply")
async def apply_organize(req: OrganizeRequest) -> dict[str, Any]:
    def _apply():
        root = Path(req.target_root).expanduser().resolve()
        moved = []
        errors = []
        for item in req.items:
            src = Path(item.source).expanduser().resolve()
            if not src.exists():
                continue
            dst_dir = root / item.category
            if req.dry_run:
                moved.append({"from": str(src), "to": str(dst_dir / src.name)})
                continue
            try:
                dst = safe_move(src, dst_dir)
                moved.append({"from": str(src), "to": str(dst)})
            except Exception as exc:
                errors.append({"file": str(src), "error": str(exc)})
        if moved and not req.dry_run:
            append_undo_entries(moved)
        return {"moved_count": len(moved), "target_root": str(root), "dry_run": req.dry_run, "errors": errors}

    return await asyncio.to_thread(_apply)


@app.post("/api/undo")
async def undo_last_batch() -> dict[str, Any]:
    def _undo():
        if not UNDO_LOG_PATH.exists():
            return {"restored_count": 0, "message": "Brak historii operacji do cofnięcia."}
        history = json.loads(UNDO_LOG_PATH.read_text())
        if not history:
            return {"restored_count": 0, "message": "Brak historii operacji do cofnięcia."}
        last = history.pop()
        restored = 0
        for m in reversed(last.get("moves", [])):
            cur = Path(m["to"])
            orig = Path(m["from"])
            if cur.exists():
                orig.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(cur), str(orig))
                restored += 1
        UNDO_LOG_PATH.write_text(json.dumps(history, indent=2, ensure_ascii=False))
        return {"restored_count": restored, "timestamp": last.get("timestamp")}

    return await asyncio.to_thread(_undo)
