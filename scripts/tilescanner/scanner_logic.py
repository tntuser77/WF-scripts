"""
scanner_logic.py

Reads and tails Warframe's EE.log looking for Void Cascade tile-setup
data (encoded as "implicit bridges" counts per zone), and reports
good/bad tile combinations.

Log format background:
    Each cascade block is a burst of lines like:
        <ts> Sys [Info]: HighLevelGraph setup <value> implicit bridges for zone <n> in <t>s total <x>
    Zone 1 always marks the start of a fresh block. The three tile IDs
    we care about are carried in the "implicit bridges" value at zone 2,
    zone 6, and zone 8.

    Blocks can be split across multiple file-tail polls, so we keep a
    persistent zone buffer (ZONE_BUFFER) that survives across polls
    instead of re-deriving a "cluster" fresh every time.
"""

import os
import re
import time
import threading
import sys

from overlay import update_overlay_data

# Global flag for signaling stop
STOP_FLAG = threading.Event()

# --- TILE DATA ---
TileData = {
    87: {"name": "Hall of legends", "value": 3},
    105: {"name": "Brig", "value": 3},
    119: {"name": "Dogshit", "value": 3},
    120: {"name": "Serenity", "value": 4},
    142: {"name": "Habitat", "value": 3},
    144: {"name": "Lunaro", "value": 3},
    162: {"name": "Angel roost", "value": 4},
    164: {"name": "Amphitheatre", "value": 3},
    226: {"name": "Albrecht park", "value": 4},
    274: {"name": "Cargo bay", "value": 3},
    402: {"name": "Hangar", "value": 5},
    493: {"name": "Schoolyard", "value": 4}
}
# --- END TILE DATA ---

# Tile IDs to hard-reject regardless of total value
BANNED_TILES = {144, 164}  # Lunaro, Amphitheatre

# --- ZONE BUFFER PARSING ---
ZONE_LINE_RE = re.compile(r"HighLevelGraph setup (\d+) implicit bridges for zone (\d+) in")
REQUIRED_ZONES = {1, 2, 6, 8}  # zone 1 = sync marker, 2/6/8 = the tile IDs we need

# Persists across polls - zone_number -> bridge_count value for the block in progress
ZONE_BUFFER = {}


def handle_new_lines(text: str):
    """Scans new log text line by line, maintaining a zone buffer that persists
    across polls. A 'zone 1' line always starts a fresh block (discarding any
    incomplete previous buffer). Fires process_tiles() the moment all
    REQUIRED_ZONES have been seen for the current block."""
    global ZONE_BUFFER

    for line in text.splitlines():
        m = ZONE_LINE_RE.search(line)
        if not m:
            continue

        value = int(m.group(1))
        zone_num = int(m.group(2))

        if zone_num == 1:
            ZONE_BUFFER = {}  # new block starting - old partial buffer is dead, drop it

        ZONE_BUFFER[zone_num] = value

        if REQUIRED_ZONES.issubset(ZONE_BUFFER.keys()):
            process_tiles(ZONE_BUFFER)
            ZONE_BUFFER = {}  # fired - clear so we don't re-fire on the same data


def process_tiles(zone_buffer: dict) -> bool:
    """Extracts tile IDs from a completed zone buffer and updates the overlay data."""
    try:
        Tile1_id = zone_buffer[2]
        Tile2_id = zone_buffer[6]
        Tile3_id = zone_buffer[8]

        Tile1_data = TileData.get(Tile1_id)
        Tile2_data = TileData.get(Tile2_id)
        Tile3_data = TileData.get(Tile3_id)

        if not all([Tile1_data, Tile2_data, Tile3_data]):
            missing_ids = [
                id_ for id_, data in zip([Tile1_id, Tile2_id, Tile3_id], [Tile1_data, Tile2_data, Tile3_data]) if data is None
            ]
            raise KeyError(missing_ids)

        Tile1_name, Tile1_value = Tile1_data["name"], Tile1_data["value"]
        Tile2_name, Tile2_value = Tile2_data["name"], Tile2_data["value"]
        Tile3_name, Tile3_value = Tile3_data["name"], Tile3_data["value"]

        TileNames = [Tile1_name, Tile2_name, Tile3_name]
        TileCount = [Tile1_value, Tile2_value, Tile3_value]
        Total_Value = sum(TileCount)

        tile_ids = [Tile1_id, Tile2_id, Tile3_id]

        if any(t in BANNED_TILES for t in tile_ids):
            status = "🔴 Bad (banned tile)"
            color = "red"
        elif Total_Value < 12:
            status = "🔴 Bad"
            color = "red"
        else:
            status = "✅ Good"
            color = "green"

        update_overlay_data(status, Total_Value, TileNames, TileCount, color)
        return True

    except KeyError as e:
        print(f"❌ Error during dictionary lookup (KeyError): Tile ID(s) not found: {e}")
    except Exception as e:
        print(f"❗ An unexpected error occurred: {e}")

    return False


# --- LOG READING / TAILING ---

def read_and_process_initial_file(filename: str):
    """Performs the initial synchronous read and processing."""
    local_appdata = os.getenv('LOCALAPPDATA')
    warframe_path = os.path.join(local_appdata, "Warframe")
    file_path = os.path.join(warframe_path, filename)

    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
            print("\n--- Scanning initial log for the most recent complete block ---")
            handle_new_lines(content)
            return file_path, len(content)

    except FileNotFoundError:
        print(f"❌ File not found: {file_path}")
    except PermissionError:
        print(f"⚠️ Permission denied: {file_path}")
    except Exception as e:
        print(f"❗ An error occurred while reading the file: {e}")

    return None, 0


def read_new_content(file_path: str, start_pos: int) -> tuple[str, int]:
    """Reads and returns whatever new bytes have been appended since start_pos."""
    try:
        current_file_size = os.path.getsize(file_path)
        if current_file_size <= start_pos:
            return "", start_pos

        bytes_to_read = current_file_size - start_pos

        with open(file_path, 'r', encoding='utf-8') as file:
            file.seek(start_pos)
            new_content = file.read(bytes_to_read)
            return new_content, current_file_size

    except Exception:
        return "", start_pos


def tail_log_sync(file_path: str, initial_pos: int, interval: float = 0.8):
    """Synchronously tails the file, feeding new lines into the zone buffer."""
    current_pos = initial_pos

    print("\nPress **ENTER** or any other key + ENTER to stop the program.\n")

    while not STOP_FLAG.is_set():
        try:
            new_text, new_pos = read_new_content(file_path, current_pos)
            current_pos = new_pos

            if new_text:
                handle_new_lines(new_text)

            time.sleep(interval)

        except KeyboardInterrupt:
            print("\n\nProgram interrupted by user (Ctrl+C).")
            STOP_FLAG.set()
        except Exception as e:
            print(f"Fatal error in log monitor: {e}")
            STOP_FLAG.set()
            break


def keypress_listener(stop_event: threading.Event):
    """Function to run in a separate thread that waits for user input."""
    try:
        sys.stdin.readline()
    except EOFError:
        pass
    except Exception as e:
        print(f"Error in keypress listener: {e}")

    print("\n\n🛑 Keypress detected. Stopping...")
    stop_event.set()
