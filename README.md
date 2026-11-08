# Readaloud

A desktop app that reads PDF and EPUB books aloud like an audiobook, using a local, offline text-to-speech engine.

![Readaloud home page with the library sidebar](docs/screenshot.png)

## Features

- **PDF and EPUB.** PDFs are read page by page. EPUBs are read chapter by chapter in spine order, with title and author taken from the book's metadata.
- **Home page and library.** The home page shows a drop area and a **Choose a file** button. Every book you add appears in a sidebar with its progress (for example "Page 40 of 210" or "Ch 3 of 12"). Click a book to continue at the exact sentence where you stopped.
- **Click any sentence** to stop the current audio and start reading from there. The sentence being read is highlighted and kept in view.
- **Clean text.** PDF running headers, footers and page numbers are removed, words split across lines are rejoined, and ligatures (ﬁ, ﬂ) are expanded. EPUB navigation, scripts, styles, images and page-break markers are stripped.
- **Careful sentence splitting** that does not break on abbreviations (Mr., Dr., e.g., i.e.), initials, decimals (3.14) or mid-sentence ellipses.
- **Scanned pages and image-only chapters are detected** and skipped with a clear message (there is no OCR).
- **Offline speech** with [Kokoro](https://github.com/hexgrad/kokoro), an 82M-parameter neural TTS model that runs locally.
- **Playback controls:** play, pause, resume, stop, previous/next page or chapter, jump to a page or chapter, and speed (0.5× to 2×).
- **Export to MP3 or WAV** for the whole book or a range of pages or chapters. Export runs in the background with a progress bar and a cancel button, and the app stays usable meanwhile.

## Supported formats

| Format | Unit | Notes |
| --- | --- | --- |
| PDF (`.pdf`) | Page | Needs a text layer; scanned pages are skipped. Password-protected PDFs are not supported. |
| EPUB (`.epub`, EPUB 2 and 3) | Chapter (one per spine document) | DRM-protected EPUBs are detected and rejected with a message. Embedded-font obfuscation is fine. |

## Requirements

- **Python 3.11 or 3.12.** Kokoro 0.9 does not support Python 3.13 yet.
- **ffmpeg**, needed by pydub for MP3 export. WAV export works without it.
- About 2 GB of disk space for PyTorch and the voice model.
- An internet connection **on first run only**: Kokoro downloads its voice model (about 330 MB) from Hugging Face, and its phonemizer downloads the small spaCy English model. After that everything runs offline.

## Installation

### 1. Install Python 3.12 and ffmpeg

macOS (Homebrew):

```bash
brew install python@3.12 ffmpeg
```

Ubuntu / Debian:

```bash
sudo apt install python3.12 python3.12-venv ffmpeg
```

Windows: install Python 3.12 from [python.org](https://www.python.org/downloads/) and ffmpeg from [ffmpeg.org](https://ffmpeg.org/download.html), then make sure `ffmpeg` is on your `PATH`.

### 2. Create a virtual environment and install Readaloud

```bash
git clone https://github.com/<your-username>/readaloud.git
cd readaloud
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Usage

### Desktop app

```bash
readaloud                 # or: python -m readaloud
readaloud path/to/book.pdf
```

The window opens on the home page: drag a PDF or EPUB onto it or click **Choose a file**. The book is added to the library sidebar and opened. Click a sentence to start reading from it. The first launch takes a little longer while the voice model loads; the status bar says when it is ready.

Adding a book that is already in the library (same contents, any file name) opens the existing entry. To remove a book, click its **✕** or right-click it and choose **Remove from library…**. This only removes Readaloud's copy and your reading position; your original file is never touched.

Set `READALOUD_LOG_LEVEL=INFO` (or `DEBUG`) to see diagnostic logging in the terminal.

| Control | Shortcut |
| --- | --- |
| Open a book | Ctrl/Cmd+O |
| Play / Pause / Resume | Space |
| Previous / Next page or chapter | Page Up / Page Down |
| Export audio | Ctrl/Cmd+E |

Speed changes take effect from the next sentence.

### Build a double-click app (macOS)

To launch Readaloud from Finder, the Dock or Launchpad with no terminal, build a standalone `Readaloud.app` with PyInstaller:

```bash
python -m pip install -e ".[app]"
python -m spacy download en_core_web_sm   # bundled so the app never needs pip
pyinstaller --noconfirm packaging/readaloud.spec
```

The app appears at `dist/Readaloud.app` (about 1 GB, mostly PyTorch). Drag it into your Applications folder, then open it and drop a PDF or EPUB onto the window. The voice model is still downloaded on first launch and cached in your user folder. MP3 export uses the system `ffmpeg` (Homebrew's is found automatically).

The same spec builds a `dist/Readaloud/` folder app on Windows and Linux. That build is untested.

### Command line

Synthesize a single page (PDF) or chapter (EPUB) to a WAV file:

```bash
readaloud-cli path/to/book.pdf --page 3 --out page3.wav --speed 1.25
readaloud-cli path/to/book.epub --chapter 2 --out chapter2.wav
```

### Run the tests

```bash
pytest
```

The tests build their own small PDFs and EPUBs at runtime and use a fake TTS engine and a temporary library folder, so they run in about a second and need neither the model nor any of your books.

## Project structure

```
readaloud/
├── src/readaloud/
│   ├── __main__.py       # GUI entry point (readaloud)
│   ├── cli.py            # single page/chapter CLI (readaloud-cli)
│   ├── document.py       # shared Document/Section model, load_document()
│   ├── pdf_extract.py    # PDF loader: PyMuPDF, header/footer/page-number cleaning
│   ├── epub_extract.py   # EPUB loader: spine order, HTML cleaning, DRM detection
│   ├── sentences.py      # regex sentence splitter, sentence positions
│   ├── tts.py            # Kokoro engine wrapper
│   ├── playback.py       # QAudioSink playback, background synthesis, reading position
│   ├── export.py         # range logic, MP3/WAV export
│   ├── library.py        # SQLite library, book copies, positions, migration
│   ├── gui.py            # main window (widgets and wiring only)
│   ├── home.py           # home page widget
│   ├── sidebar.py        # library sidebar widget
│   └── export_dialog.py  # export range dialog and worker thread
├── tests/                # pytest suite; generates its own PDFs and EPUBs
├── packaging/            # PyInstaller spec and launcher for Readaloud.app
├── docs/                 # screenshot
├── pyproject.toml
├── LICENSE
└── README.md
```

Both loaders produce the same `Document` (metadata plus numbered sections, each split into sentences), so playback, export and the library never need to know whether a book came from a PDF or an EPUB. The GUI modules hold no parsing or TTS logic.

## Where data is stored

The library lives in your platform's user data directory (via `platformdirs`), never inside the repository:

| OS | Folder |
| --- | --- |
| macOS | `~/Library/Application Support/readaloud/` |
| Linux | `~/.local/share/readaloud/` (or `$XDG_DATA_HOME/readaloud/`) |
| Windows | `%LOCALAPPDATA%\readaloud\` |

Inside it:

- `library.sqlite3`: one row per book with its title, author, format, progress and reading position (page or chapter, plus sentence).
- `books/`: Readaloud's own copy of each book, named by the SHA-256 of its contents. The library keeps working if you move or delete the original file.

Only the original file *name* is stored for reference, never its folder path. To reset everything, quit the app and delete that folder.

**Upgrading from an earlier version:** positions saved in the old `resume_positions.json` are imported automatically on first start. A book picks up its saved page the first time you add that same file again. The old file is left in place.

## Known limitations

- **No OCR.** Scanned or image-only pages are skipped.
- **EPUB chapters follow the book's files.** Each spine document is one chapter. Some books put several chapters in one file (or split one chapter across files), so "chapter" counts and export ranges follow the file layout, not necessarily the printed chapters.
- **DRM-protected EPUBs** (Adobe, Apple, Kindle conversions with DRM) cannot be read.
- **Sentence splitting is rule-based.** It handles common English abbreviations, initials, acronyms, decimals and ellipses, but an unusual abbreviation followed by a capitalised word can still split a sentence in two, or join two sentences.
- **English only.** The app uses Kokoro's American English voice `af_heart`. Other languages and voices are not exposed in the UI.
- **Header/footer detection is heuristic.** It removes text in the top and bottom margins that repeats on at least 30% of pages, plus bare page numbers. Unusual layouts can leave a header in or, rarely, drop a repeated line. Multi-column layouts and tables are read in PyMuPDF's block order.
- **Paragraphs that cross a PDF page break** are read as two pieces, with a short pause between them.
- **Speed changes** apply from the next sentence, not mid-sentence.
- **Synthesis speed depends on your CPU/GPU.** On slow machines there can be a short pause between sentences, and exporting a whole book can take a long time.
- **Long exports to MP3** are converted in memory by pydub at the end, which needs RAM roughly the size of the uncompressed audio (about 170 MB per hour). WAV export streams to disk.
- **Install path length:** espeak-ng (used by Kokoro's phonemizer) fails with `Error processing file '.../phontab'` if the virtual environment is in a very deep directory (around 160 characters to the `espeak-ng-data` folder). Use a shorter path if you see this.
- Python 3.13 is not supported because of Kokoro, and pydub relies on the `audioop` module that 3.13 removed.

## License

[MIT](LICENSE)
