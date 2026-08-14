"""
overlay.py

Tkinter overlay window that displays the current tile scan status.
The scanning logic (scanner_logic.py) writes into OVERLAY_DATA;
this module just reads it and renders it.
"""

import tkinter as tk
from tkinter import font as tkfont

# --- GLOBAL DATA FOR OVERLAY COMMUNICATION ---
# The scanner logic thread writes to this, and the GUI thread reads from it.
OVERLAY_DATA = {
    "status": "Waiting for map...",
    "names": [],
    "values": [],
    "total": 0,
    "color": "yellow"
}
# --- END GLOBAL DATA ---


def update_overlay_data(status, total, names, values, color):
    """Updates the global data structure for the overlay."""
    global OVERLAY_DATA
    OVERLAY_DATA.update({
        "status": status,
        "total": total,
        "names": names,
        "values": values,
        "color": color
    })
    # Also print to console for backup/debugging
    print("\n====================================")
    print(f"[{status}] Total: {total}")
    print(f"Tile Names: {', '.join(names)}")
    print(f"Tile Values: {values}")
    print("====================================")


class OverlayApp(tk.Tk):
    def __init__(self, stop_event):
        super().__init__()
        self.stop_event = stop_event
        self.title("Warframe Tile Monitor")

        # --- Window Configuration for Overlay ---
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.attributes('-alpha', 0.95)

        # Initial position (Top center of the screen)
        screen_width = self.winfo_screenwidth()
        window_width = 400
        window_height = 80
        x_pos = (screen_width // 2) - (window_width // 2)
        y_pos = 10
        self.geometry(f'{window_width}x{window_height}+{x_pos}+{y_pos}')

        # --- UI Elements ---
        self.configure(bg='black')

        self.status_font = tkfont.Font(family="Arial", size=14, weight="bold")
        self.tile_font = tkfont.Font(family="Arial", size=10)

        self.status_label = tk.Label(
            self,
            text="Waiting for map...",
            font=self.status_font,
            fg="yellow",
            bg="black"
        )
        self.status_label.pack(pady=(5, 0))

        self.tiles_label = tk.Label(
            self,
            text="",
            font=self.tile_font,
            fg="white",
            bg="black"
        )
        self.tiles_label.pack()

        self.update_ui()
        self.after(500, self.periodic_check)

    def periodic_check(self):
        """Checks the global data and updates the UI."""
        if self.stop_event.is_set():
            self.destroy()
            return

        self.update_ui()
        self.after(500, self.periodic_check)

    def update_ui(self):
        """Updates the labels based on the global OVERLAY_DATA."""
        status_text = f"{OVERLAY_DATA['status']} (Total: {OVERLAY_DATA['total']})"
        self.status_label.config(
            text=status_text,
            fg=OVERLAY_DATA['color']
        )

        if OVERLAY_DATA['names']:
            names = OVERLAY_DATA['names']
            values = OVERLAY_DATA['values']
            tiles_text = ", ".join([f"{n} ({v})" for n, v in zip(names, values)])
        else:
            tiles_text = "..."

        self.tiles_label.config(text=tiles_text)


def start_overlay(stop_event):
    """Initializes and runs the Tkinter overlay application."""
    try:
        app = OverlayApp(stop_event)
        app.mainloop()
    except Exception as e:
        print(f"\nOverlay failed to start/run: {e}")
        stop_event.set()
