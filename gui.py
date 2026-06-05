"""AiTorrent - GUI application."""

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading

from download_engine import DownloadEngine


class TorrentRow:
    def __init__(self, frame: tk.Frame, name: str, total: int):
        self.engine: DownloadEngine | None = None
        self.total = total

        self.container = tk.Frame(frame, bg="#1e1e2e", pady=6, padx=10)
        self.container.pack(fill="x", pady=2)

        # Name label
        self.name_lbl = tk.Label(self.container, text=name, fg="#cdd6f4",
                                 bg="#1e1e2e", font=("Segoe UI", 10, "bold"),
                                 anchor="w")
        self.name_lbl.pack(fill="x")

        # Size + speed row
        info_row = tk.Frame(self.container, bg="#1e1e2e")
        info_row.pack(fill="x")
        size_str = _fmt_size(total)
        self.size_lbl = tk.Label(info_row, text=size_str, fg="#a6adc8",
                                 bg="#1e1e2e", font=("Segoe UI", 8))
        self.size_lbl.pack(side="left")
        self.speed_lbl = tk.Label(info_row, text="", fg="#89b4fa",
                                  bg="#1e1e2e", font=("Segoe UI", 8))
        self.speed_lbl.pack(side="right")

        # Progress bar
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Torrent.Horizontal.TProgressbar",
                        troughcolor="#313244", background="#89b4fa",
                        thickness=6)
        self.progress = ttk.Progressbar(self.container, style="Torrent.Horizontal.TProgressbar",
                                        maximum=100, value=0)
        self.progress.pack(fill="x", pady=(4, 2))

        # Status
        self.status_lbl = tk.Label(self.container, text="Starting...",
                                   fg="#a6adc8", bg="#1e1e2e", font=("Segoe UI", 8))
        self.status_lbl.pack(anchor="w")

        # Separator
        sep = tk.Frame(frame, height=1, bg="#313244")
        sep.pack(fill="x")

    def update_progress(self, done: int, total: int, speed: float):
        pct = (done / total * 100) if total > 0 else 0
        self.progress["value"] = pct
        speed_str = f"{_fmt_size(speed)}/s" if speed > 0 else ""
        self.speed_lbl.config(text=speed_str)

    def update_status(self, msg: str):
        self.status_lbl.config(text=msg)


def _fmt_size(b: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AiTorrent")
        self.geometry("600x500")
        self.configure(bg="#1e1e2e")
        self.resizable(True, True)

        self._rows: list[TorrentRow] = []
        self._engines: list[DownloadEngine] = []
        self._download_dir = os.path.expanduser("~/Downloads")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # Header
        header = tk.Frame(self, bg="#181825", pady=10)
        header.pack(fill="x")
        tk.Label(header, text="  AiTorrent", fg="#cba6f7", bg="#181825",
                 font=("Segoe UI", 16, "bold")).pack(side="left")

        btn_frame = tk.Frame(header, bg="#181825")
        btn_frame.pack(side="right", padx=10)

        add_btn = tk.Button(btn_frame, text="+ Add Torrent",
                            bg="#89b4fa", fg="#1e1e2e",
                            font=("Segoe UI", 9, "bold"),
                            relief="flat", padx=10, pady=4,
                            cursor="hand2", command=self._add_torrent)
        add_btn.pack(side="left", padx=4)

        dir_btn = tk.Button(btn_frame, text="Save folder",
                            bg="#313244", fg="#cdd6f4",
                            font=("Segoe UI", 9),
                            relief="flat", padx=10, pady=4,
                            cursor="hand2", command=self._pick_dir)
        dir_btn.pack(side="left", padx=4)

        # Scroll area
        self._canvas = tk.Canvas(self, bg="#1e1e2e", highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._canvas.pack(fill="both", expand=True)

        self._list_frame = tk.Frame(self._canvas, bg="#1e1e2e")
        self._canvas_win = self._canvas.create_window((0, 0), window=self._list_frame, anchor="nw")
        self._list_frame.bind("<Configure>", self._on_frame_resize)
        self._canvas.bind("<Configure>", self._on_canvas_resize)

        # Footer
        footer = tk.Frame(self, bg="#181825", pady=6)
        footer.pack(fill="x", side="bottom")
        self._dir_lbl = tk.Label(footer, text=f"Save to: {self._download_dir}",
                                 fg="#585b70", bg="#181825", font=("Segoe UI", 8))
        self._dir_lbl.pack(side="left", padx=10)

    def _on_frame_resize(self, event):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_resize(self, event):
        self._canvas.itemconfig(self._canvas_win, width=event.width)

    def _pick_dir(self):
        d = filedialog.askdirectory(title="Choose download folder",
                                    initialdir=self._download_dir)
        if d:
            self._download_dir = d
            self._dir_lbl.config(text=f"Save to: {d}")

    def _add_torrent(self):
        path = filedialog.askopenfilename(
            title="Open .torrent file",
            filetypes=[("Torrent files", "*.torrent"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            self._start_download(path)
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _start_download(self, torrent_path: str):
        engine = DownloadEngine(torrent_path, self._download_dir)
        row = TorrentRow(self._list_frame, engine.name, engine.total_length)
        row.engine = engine
        self._rows.append(row)
        self._engines.append(engine)

        def on_progress(done, total, speed):
            self.after(0, row.update_progress, done, total, speed)

        def on_status(msg):
            self.after(0, row.update_status, msg)

        engine.on_progress = on_progress
        engine.on_status = on_status
        engine.start()

    def _on_close(self):
        for e in self._engines:
            e.stop()
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
