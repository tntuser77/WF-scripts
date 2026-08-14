"""
main.py

Entry point. Starts the log-tailing scanner (scanner_logic.py) and the
Tkinter overlay (overlay.py) as separate threads.
"""

import sys
import threading

from overlay import start_overlay
from scanner_logic import (
    STOP_FLAG,
    read_and_process_initial_file,
    tail_log_sync,
    keypress_listener,
)


def main_sync():
    """The main entry point, coordinating the log-tailing and overlay threads."""

    FILE_NAME = "EE.log"
    file_path, initial_file_pos = read_and_process_initial_file(FILE_NAME)

    if not file_path or initial_file_pos == 0:
        print("\nCannot start log monitor. Press ENTER to exit.")
        input()
        return

    # 1. Start the keypress listener thread (to stop the whole program)
    listener_thread = threading.Thread(
        target=keypress_listener,
        args=(STOP_FLAG,),
        daemon=True
    )
    listener_thread.start()

    # 2. Start the GUI overlay thread
    overlay_thread = threading.Thread(
        target=start_overlay,
        args=(STOP_FLAG,),
        daemon=True
    )
    print("Starting graphical overlay...")
    overlay_thread.start()

    # 3. Synchronous log tailing in the main thread
    try:
        tail_log_sync(file_path, initial_file_pos)
    except Exception as e:
        print(f"An unexpected error occurred in the main loop: {e}")
    finally:
        STOP_FLAG.set()
        listener_thread.join(timeout=1)
        overlay_thread.join(timeout=1)
        print("✅ Program ended.")


if __name__ == "__main__":
    if sys.stdin.isatty():
        main_sync()
    else:
        print("Error: Script requires an interactive terminal for keypress detection.")
