# Setup Instructions

Follow these steps to get MD Vault running on your own machine. Everything
runs locally - no accounts, no API keys, no data ever leaves your computer.

## 1. Get the code

```bash
git clone https://github.com/yashduttrading-ui/Shikhara-Distill-converts-documents-to-md-files-.git
cd Shikhara-Distill-converts-documents-to-md-files-
```

## 2. Install Python dependencies

```bash
pip install -r requirements.txt
chmod +x start.sh converter.py query.py
```

## 3. (Optional) Install Tesseract for OCR

Only needed if you'll be converting **scanned/image-only PDFs**. Normal
text-based PDFs/DOCX/XLSX/CSV work fine without it.

```bash
brew install tesseract
```

(On Linux, use your package manager, e.g. `sudo apt install tesseract-ocr`.)

## 4. Start the watcher

```bash
./start.sh start    # start the background watcher
./start.sh status    # check it's running
./start.sh stop      # stop it
```

## 5. Use it

Drop a PDF/DOCX/XLSX/CSV into the `watched/` folder. Within a couple seconds,
check the `markdown/` folder for:

- `<filename>.md` - the full converted document
- `<filename>/` - a folder with each major section/company split into its
  own small `.md` file, ready to upload to an AI chat

See [README.md](README.md) for more details on how conversion and section
splitting work, plus the optional `distill` query tool.
