"""Desktop-Start: dieselbe Web-App in einem nativen Fenster (wie Notion).

Startet den FastAPI-Server lokal in einem Hintergrund-Thread und öffnet ihn in
einem nativen Fenster via pywebview. Identische Funktionalität wie die Web-App,
nur als eigenständige Anwendung.

Voraussetzung:  pip install pywebview
Start:          python desktop.py

Daraus eine .exe (Windows) bzw. .app (macOS) bauen — auf dem jeweiligen
Betriebssystem ausführen:
    pip install pyinstaller pywebview
    pyinstaller --noconfirm --windowed --name "Fertigungs-OS" \
        --add-data "static:static" desktop.py
Das Ergebnis liegt in dist/. (Eine Windows-.exe muss unter Windows gebaut
werden, eine macOS-.app unter macOS — Cross-Build ist nicht möglich.)
"""

import threading
import time

import uvicorn

from app.main import app

HOST, PORT = "127.0.0.1", 8000


def _run_server() -> None:
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def main() -> None:
    threading.Thread(target=_run_server, daemon=True).start()
    time.sleep(1.5)  # Server-Start abwarten
    try:
        import webview  # pywebview
    except ImportError:
        raise SystemExit(
            "pywebview fehlt. Installieren mit:  pip install pywebview\n"
            "Alternativ die Web-App im Browser nutzen: http://127.0.0.1:8000"
        )
    webview.create_window("Fertigungs-Betriebssystem", f"http://{HOST}:{PORT}",
                          width=1400, height=900)
    webview.start()


if __name__ == "__main__":
    main()
