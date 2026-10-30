import ctypes
import json
import queue
import tkinter as tk
from speech_engine import SpeechEngine
from pathlib import Path

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# ============================================================
# FILES AND SETTINGS
# ============================================================

APP_DIR = Path(__file__).resolve().parent
DATA_FILE = APP_DIR / "note_data.json"
WOLF_FILE = APP_DIR / "wolf.png"
OPEN_SOUND = APP_DIR / "Cara-Delevingne-Voice-open.mp3"
CLOSE_SOUND = APP_DIR / "Cara-Delevingne-Voice-closed.mp3"

NOTE_W, NOTE_H = 320, 460
ICON_SIZE = 96

BG = "#202124"
PANEL = "#292a2d"
TEXT = "#e8eaed"
MUTED = "#9aa0a6"
ACCENT = "#8ab4f8"
BORDER = "#3c4043"
TRANSPARENT_KEY = "#ff00ff"

# Windows redraw flags. These are only used if Windows exposes the
# native window handle; the app still works if the call is unavailable.
RDW_INVALIDATE = 0x0001
RDW_UPDATENOW = 0x0100
RDW_ALLCHILDREN = 0x0080

data = {}
wolf = None
wolf_image = None
fold_button_image = None
_save_job = None
speak_active = False
transparent_supported = False
_last_editor_text = None


def load_data():
    try:
        loaded = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


data = load_data()
sound_muted = bool(data.get("sound_muted", False))


# ============================================================
# MAIN WINDOW
# ============================================================

root = tk.Tk()
root.withdraw()
root.title("Desktop Sticky Note")
root.configure(bg=BG)
root.minsize(260, 330)
root.geometry(data.get("geometry", f"{NOTE_W}x{NOTE_H}+80+80"))

top_var = tk.BooleanVar(value=bool(data.get("always_on_top", True)))
root.attributes("-topmost", top_var.get())

status_var = tk.StringVar(value="Auto-saves as you type")


def show_note_without_taskbar():
    """Try to keep the main note off the Windows taskbar."""
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())

        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000

        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

        user32.SetWindowLongW(
            hwnd,
            GWL_EXSTYLE,
            (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW,
        )
        root.update_idletasks()

    except (AttributeError, OSError, tk.TclError) as error:
        print(f"Could not hide taskbar icon: {error}")


root.after(100, show_note_without_taskbar)


# ============================================================
# SOUND
# ============================================================

def play_sound(sound_file):
    if sound_muted or not sound_file.is_file():
        return

    try:
        import pygame

        if not pygame.mixer.get_init():
            pygame.mixer.init()

        pygame.mixer.music.load(str(sound_file))
        pygame.mixer.music.play()

    except Exception as error:
        print(f"Could not play sound: {error}")


# ============================================================
# SAVE DATA
# ============================================================

def save_data():
    global _save_job

    _save_job = None

    try:
        if root.winfo_exists():
            data["geometry"] = root.geometry()
            data["always_on_top"] = bool(top_var.get())

        if editor.winfo_exists():
            data["text"] = editor.get("1.0", "end-1c")

        data["sound_muted"] = sound_muted

        if wolf is not None:
            try:
                if wolf.winfo_exists():
                    data["wolf_position"] = (
                        f"{wolf.winfo_x():+d}{wolf.winfo_y():+d}"
                    )
            except tk.TclError:
                pass

        temporary_file = DATA_FILE.with_suffix(".tmp")
        temporary_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_file.replace(DATA_FILE)

        status_var.set("Saved")

    except (OSError, tk.TclError, NameError) as error:
        print(f"Could not save note: {error}")


def schedule_save(event=None):
    global _save_job

    if _save_job is not None:
        try:
            root.after_cancel(_save_job)
        except tk.TclError:
            pass

    try:
        status_var.set("Typing…")
        _save_job = root.after(800, save_data)
    except tk.TclError:
        _save_job = None


# ============================================================
# HEADER
# ============================================================

header = tk.Frame(root, bg=PANEL, padx=8, pady=7)
header.pack(fill="x")

title_label = tk.Label(
    header,
    text="",
    bg=PANEL,
    fg=ACCENT,
    font=("Segoe UI", 10, "bold"),
)
title_label.pack(side="left")


def set_topmost():
    enabled = bool(top_var.get())
    root.attributes("-topmost", enabled)

    if enabled:
        root.lift()
    else:
        root.attributes("-topmost", False)
        root.lower()

    save_data()


pin_button = tk.Checkbutton(
    header,
    text="On top",
    variable=top_var,
    command=set_topmost,
    bg=PANEL,
    fg=TEXT,
    selectcolor=BG,
    activebackground=PANEL,
    activeforeground=TEXT,
    font=("Segoe UI", 9),
    bd=0,
)
pin_button.pack(side="right", padx=(4, 0))


# ============================================================
# LOCAL SPEECH-TO-TEXT (NO WINDOWS VOICE TYPING)
# ============================================================

speech_engine = SpeechEngine(model_size="large-v3-turbo")
speech_messages = speech_engine.messages

# Preload Whisper in the background during app startup.
speech_engine.preload()


def set_speech_button(active, loading=False):
    global speak_active
    speak_active = active

    if loading:
        text = "🎙 LOADING…"
        color = "#9A6700"
    elif active:
        text = "🎙 LISTENING"
        color = "#16803C"
    else:
        text = "🎙 SPEAK"
        color = "#34465c"

    speak_button.config(
        text=text,
        bg=color,
        activebackground=color,
        fg="white",
        activeforeground="white",
    )


def start_dictation():
    if speak_active:
        speech_engine.stop()
        set_speech_button(False)
        status_var.set("Stopping speech recognition…")
        return

    root.deiconify()
    root.lift()
    root.attributes("-topmost", bool(top_var.get()))
    editor.focus_force()
    editor.mark_set("insert", "end-1c")
    editor.see("insert")

    started = speech_engine.start()
    if started:
        set_speech_button(True, loading=True)
        status_var.set("Loading speech model… first start can take a little while")
    else:
        status_var.set("Speech recognizer is still starting or stopping; try again in a moment")


def poll_speech_messages():
    """Apply worker-thread messages only on Tk's main thread."""
    try:
        if not root.winfo_exists():
            return

        while True:
            try:
                message = speech_messages.get_nowait()
            except queue.Empty:
                break

            kind = message[0]
            if kind == "status":
                status_var.set(message[1])
                if message[1].startswith("Listening"):
                    set_speech_button(True)
            elif kind == "text":
                text, language = message[1], message[2]
                if text.strip():
                    existing = editor.get("1.0", "end-1c")
                    prefix = "" if not existing or existing[-1].isspace() else " "
                    editor.insert("insert", prefix + text.strip())
                    editor.see("insert")
                    editor.focus_set()
                    schedule_save()
                    status_var.set(f"Recognised language: {language.upper()} — listening…")
            elif kind == "error":
                set_speech_button(False)
                status_var.set("Speech error: " + message[1])
            elif kind == "stopped":
                set_speech_button(False)
                status_var.set("Speech recognition stopped")

        root.after(100, poll_speech_messages)
    except tk.TclError:
        pass


speak_button = tk.Button(
    header,
    text="🎙 SPEAK",
    command=start_dictation,
    bg="#34465c",
    fg="white",
    activebackground="#466080",
    activeforeground="white",
    relief="flat",
    bd=0,
    font=("Segoe UI", 8),
    cursor="hand2",
    padx=5,
    pady=1,
)
speak_button.pack(side="right", padx=(2, 0))


# ============================================================
# MUTE BUTTON
# ============================================================

def toggle_sound():
    global sound_muted

    sound_muted = not sound_muted
    update_sound_button()
    save_data()


def update_sound_button():
    if sound_muted:
        sound_button.config(
            text="SOUND: MUTED",
            bg="#C62828",
            activebackground="#A51F1F",
        )
    else:
        sound_button.config(
            text="SOUND: ON",
            bg="#16803C",
            activebackground="#11652F",
        )


sound_button = tk.Button(
    header,
    text="",
    command=toggle_sound,
    bg="#16803C",
    fg="white",
    activebackground="#11652F",
    activeforeground="white",
    relief="flat",
    bd=0,
    font=("Segoe UI", 7, "bold"),
    cursor="hand2",
    padx=8,
    pady=2,
)
sound_button.pack(side="right", padx=(2, 0))
update_sound_button()


# ============================================================
# NOTE EDITOR
# ============================================================

body = tk.Frame(root, bg=BG, padx=10, pady=10)
body.pack(fill="both", expand=True)

editor = tk.Text(
    body,
    wrap="word",
    undo=True,
    bg=BG,
    fg=TEXT,
    insertbackground=TEXT,
    selectbackground="#3c5a7a",
    relief="flat",
    bd=0,
    font=("Segoe UI", 11),
    padx=3,
    pady=3,
    spacing1=2,
    spacing3=4,
    highlightthickness=1,
    highlightbackground=BORDER,
    highlightcolor=ACCENT,
)
editor.pack(fill="both", expand=True)
editor.insert("1.0", str(data.get("text", "")))
editor.edit_modified(False)


# ============================================================
# FOOTER
# ============================================================

footer = tk.Frame(root, bg=PANEL, padx=10, pady=7)
footer.pack(fill="x")

tk.Label(
    footer,
    textvariable=status_var,
    bg=PANEL,
    fg=MUTED,
    font=("Segoe UI", 8),
).pack(side="left")


def clear_note():
    if editor.get("1.0", "end-1c").strip():
        editor.delete("1.0", "end")
        editor.focus_set()
        save_data()


clear_btn = tk.Button(
    footer,
    text="Clear",
    command=clear_note,
    bg=BORDER,
    fg=TEXT,
    activebackground="#5f6368",
    activeforeground=TEXT,
    relief="flat",
    bd=0,
    padx=10,
    pady=4,
    font=("Segoe UI", 9),
)
clear_btn.pack(side="right")


# ============================================================
# WOLF IMAGE AND FLOATING ICON
# ============================================================

def load_wolf_image():
    """Load the original wolf.png for the compact floating icon."""
    if not WOLF_FILE.is_file():
        print(f"wolf.png was not found at: {WOLF_FILE}")
        return None

    try:
        if PIL_AVAILABLE:
            image = Image.open(WOLF_FILE).convert("RGBA")
            image = image.resize(
                (ICON_SIZE, ICON_SIZE),
                Image.Resampling.LANCZOS,
            )

            pixels = image.load()

            for y in range(image.height):
                for x in range(image.width):
                    r, g, b, a = pixels[x, y]

                    if a < 128:
                        pixels[x, y] = (255, 0, 255, 255)
                    else:
                        pixels[x, y] = (r, g, b, 255)

            return ImageTk.PhotoImage(image)

        image = tk.PhotoImage(file=str(WOLF_FILE))

        if image.width() != ICON_SIZE or image.height() != ICON_SIZE:
            factor = max(
                1,
                image.width() // ICON_SIZE,
                image.height() // ICON_SIZE,
            )
            image = image.subsample(factor, factor)

        return image

    except (tk.TclError, OSError, ValueError) as error:
        print(f"Could not load wolf.png: {error}")
        return None


def parse_position(position):
    """Read saved Tk positions, including negative screen coordinates."""
    import re

    match = re.search(r"([+-]\d+)([+-]\d+)$", str(position))

    if match:
        return int(match.group(1)), int(match.group(2))

    return 80, 80


def collapse_note():
    global wolf, wolf_image, transparent_supported

    if wolf is not None:
        try:
            if wolf.winfo_exists():
                return
        except tk.TclError:
            pass

    save_data()

    if not getattr(root, "_starting_compact", False):
        play_sound(CLOSE_SOUND)

    x, y = parse_position(data.get("wolf_position", "+80+80"))
    root.withdraw()

    wolf = tk.Toplevel(root)
    wolf.overrideredirect(True)
    wolf.geometry(f"{ICON_SIZE}x{ICON_SIZE}{x:+d}{y:+d}")
    wolf.attributes("-topmost", True)

    try:
        wolf.configure(bg=TRANSPARENT_KEY)
        wolf.wm_attributes("-transparentcolor", TRANSPARENT_KEY)
        transparent_supported = True
    except tk.TclError:
        transparent_supported = False
        wolf.configure(bg=BG)

    wolf_image = load_wolf_image()
    icon_bg = TRANSPARENT_KEY if transparent_supported else BG

    if wolf_image is not None:
        wolf_label = tk.Label(
            wolf,
            image=wolf_image,
            bg=icon_bg,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )
    else:
        wolf_label = tk.Label(
            wolf,
            text="🐺",
            bg=icon_bg,
            fg=ACCENT,
            font=("Segoe UI Emoji", 30),
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )

    wolf_label.pack(fill="both", expand=True)

    drag = {
        "offset_x": 0,
        "offset_y": 0,
        "start_x": 0,
        "start_y": 0,
        "moved": False,
    }

    def start_drag(event):
        drag["offset_x"] = event.x_root - wolf.winfo_x()
        drag["offset_y"] = event.y_root - wolf.winfo_y()
        drag["start_x"] = event.x_root
        drag["start_y"] = event.y_root
        drag["moved"] = False

    def move_drag(event):
        dx = event.x_root - drag["start_x"]
        dy = event.y_root - drag["start_y"]

        if abs(dx) > 4 or abs(dy) > 4:
            drag["moved"] = True

        if drag["moved"]:
            new_x = event.x_root - drag["offset_x"]
            new_y = event.y_root - drag["offset_y"]
            wolf.geometry(
                f"{ICON_SIZE}x{ICON_SIZE}{new_x:+d}{new_y:+d}"
            )

    def finish_drag(event):
        if drag["moved"]:
            save_data()
        else:
            restore_note()

    for widget in (wolf, wolf_label):
        widget.bind("<Button-1>", start_drag)
        widget.bind("<B1-Motion>", move_drag)
        widget.bind("<ButtonRelease-1>", finish_drag)


def restore_note():
    global wolf, wolf_image

    if wolf is not None:
        try:
            wolf.destroy()
        except tk.TclError:
            pass

    wolf = None
    wolf_image = None

    play_sound(OPEN_SOUND)

    root.withdraw()
    root.after(10, root.deiconify)
    root.after(30, root.lift)
    root.after(50, lambda: root.attributes("-topmost", bool(top_var.get())))
    root.after(100, editor.focus_set)
    root.after(150, save_data)


# Preserve the wolf image on the header's fold button.
try:
    fold_button_image = tk.PhotoImage(file=str(WOLF_FILE))
except (tk.TclError, OSError) as error:
    print(f"Could not load wolf.png for the fold button: {error}")
    fold_button_image = None


fold_button = tk.Button(
    header,
    image=fold_button_image,
    text="" if fold_button_image is not None else "🐺",
    command=collapse_note,
    bg=PANEL,
    fg=TEXT,
    activebackground=BORDER,
    relief="flat",
    bd=0,
    cursor="hand2",
    padx=5,
)
fold_button.pack(side="right")


# ============================================================
# EDITOR EVENTS AND AUTOSAVE
# ============================================================

def redraw_editor():
    """Request a native Windows repaint without changing keyboard focus."""
    try:
        if not editor.winfo_exists() or not root.winfo_exists():
            return

        root.update_idletasks()

        if hasattr(ctypes, "windll"):
            user32 = ctypes.windll.user32
            flags = RDW_INVALIDATE | RDW_UPDATENOW | RDW_ALLCHILDREN

            editor_hwnd = editor.winfo_id()
            client_hwnd = root.winfo_id()
            outer_hwnd = user32.GetParent(client_hwnd)

            user32.RedrawWindow(editor_hwnd, None, None, flags)
            user32.UpdateWindow(editor_hwnd)
            user32.RedrawWindow(client_hwnd, None, None, flags)
            user32.UpdateWindow(client_hwnd)

            if outer_hwnd:
                user32.RedrawWindow(outer_hwnd, None, None, flags)
                user32.UpdateWindow(outer_hwnd)

    except (AttributeError, OSError, tk.TclError):
        pass


def on_editor_modified(event=None):
    if editor.edit_modified():
        editor.edit_modified(False)
        schedule_save()
        root.after_idle(redraw_editor)


editor.bind("<<Modified>>", on_editor_modified)


def poll_editor_text():
    """
    Windows Voice Typing can insert text without consistently triggering
    Tk's Modified virtual event. Poll the text itself as a fallback.
    When content changes, autosave and request a native widget redraw.
    """
    global _last_editor_text

    try:
        if not root.winfo_exists() or not editor.winfo_exists():
            return

        current_text = editor.get("1.0", "end-1c")

        if _last_editor_text is None:
            _last_editor_text = current_text
        elif current_text != _last_editor_text:
            _last_editor_text = current_text
            schedule_save()
            root.after_idle(redraw_editor)

        root.after(150, poll_editor_text)

    except tk.TclError:
        pass


def on_configure(event):
    if event.widget == root and root.state() == "normal":
        schedule_save()


root.bind("<Configure>", on_configure)


# ============================================================
# STARTUP AND SHUTDOWN
# ============================================================

def start_compact_silently():
    root._starting_compact = True

    try:
        collapse_note()
    finally:
        root._starting_compact = False


def close_app():
    save_data()

    try:
        speech_engine.stop()
    except Exception:
        pass

    try:
        import pygame

        if pygame.mixer.get_init():
            pygame.mixer.quit()
    except Exception:
        pass

    try:
        if wolf is not None and wolf.winfo_exists():
            wolf.destroy()
    except tk.TclError:
        pass

    root.destroy()


root.protocol("WM_DELETE_WINDOW", close_app)

# Start the text-change monitor and speech-message pump.
_last_editor_text = editor.get("1.0", "end-1c")
root.after(150, poll_editor_text)
root.after(100, poll_speech_messages)

root.withdraw()
root.after(500, start_compact_silently)

root.mainloop()
