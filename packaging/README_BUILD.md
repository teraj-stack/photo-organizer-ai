# Budowanie instalatora DMG dla Photo Organizer AI (macOS)

Ten katalog zawiera wszystkie pliki potrzebne do zapakowania aplikacji **Photo Organizer AI** jako samodzielnego pliku `.app` oraz instalatora `.dmg` do przenoszenia między komputerami Mac (Apple Silicon `arm64`).

## Pliki
- `launcher.py` — punkt startowy aplikacji `.app`: automatycznie uruchamia serwer FastAPI na wolnym porcie, zapisuje dziennik Undo w `~/Library/Application Support/PhotoOrganizerAI/` i otwiera interfejs w przeglądarce.
- `build_dmg.sh` — pełny skrypt budujący ikonę `.icns`, paczkę `dist/Photo Organizer AI.app` (przez PyInstaller) oraz instalator `dist/Photo-Organizer-AI-macOS-arm64.dmg` (ze skrótem do `/Applications`).

## Jak zbudować plik DMG
W terminalu (najlepiej po zakończeniu bieżącej analizy zdjęć, żeby nie obciążać RAM-u):

```bash
cd /Users/krzysztofjarzyna/.gemini/antigravity/scratch/photo-organizer-ai
./packaging/build_dmg.sh
```

Gotowy plik pojawi się w:
`dist/Photo-Organizer-AI-macOS-arm64.dmg`

## Pierwsze uruchomienie na innym Macu
Ponieważ aplikacja jest podpisana lokalnie (ad-hoc, bez płatnego certyfikatu Apple Developer ID), przy pierwszym uruchomieniu na innym Macu:
1. Przeciągnij **Photo Organizer AI.app** do folderu **Applications**.
2. Kliknij prawym przyciskiem → **Otwórz** (albo w terminalu wykonaj `xattr -cr "/Applications/Photo Organizer AI.app"`).
3. Do klasyfikacji offline na docelowym Macu zainstaluj dodatkowo [Ollama](https://ollama.com) i model `qwen2.5vl:7b` (albo użyj klucza Gemini API).
