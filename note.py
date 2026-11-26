import ctypes
import json
import queue
import tkinter as tk
from tkinter import messagebox, simpledialog
import uuid
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
OPEN_SOUND = APP_DIR / "Cara-Delevingne-Voice-open-louder.mp3"
CLOSE_SOUND = APP_DIR / "Cara-Delevingne-Voice-closed-louder.mp3"

NOTE_W, NOTE_H = 440, 460
ICON_SIZE = 96

BG = "#202124"
PANEL = "#292a2d"
TEXT = "#FFFFFF"
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

# Conversations are stored independently in note_data.json.
# Older versions stored only one text field; migrate it into the first tab.
conversations = data.get("conversations", [])
if not isinstance(conversations, list):
    conversations = []

clean_conversations = []
for item in conversations:
    if isinstance(item, dict):
        clean_conversations.append({
            "id": str(item.get("id") or uuid.uuid4().hex),
            "title": str(item.get("title") or "New conversation"),
            "custom_title": bool(item.get("custom_title", False)),
            "text": str(item.get("text", "")),
            "tab_color": item.get("tab_color"),
        })
conversations = clean_conversations

if not conversations:
    conversations = [{
        "id": uuid.uuid4().hex,
        "title": "New conversation",
        "custom_title": False,
        "text": str(data.get("text", "")),
    }]

active_conversation_id = str(data.get("active_conversation_id", ""))
if not any(item["id"] == active_conversation_id for item in conversations):
    active_conversation_id = conversations[0]["id"]

_last_tab_title = None


# ============================================================
# MAIN WINDOW
# ============================================================

root = tk.Tk()
root.withdraw()
root.title("Nexus Wake Word")
root.configure(bg=BG)
root.minsize(430, 330)
root.geometry(data.get("geometry", f"{NOTE_W}x{NOTE_H}+80+80"))

top_var = tk.BooleanVar(value=bool(data.get("always_on_top", True)))
root.attributes("-topmost", top_var.get())

status_var = tk.StringVar(value="Auto-saves as you type")
SUPPORTED_SPEECH_LANGUAGES = {
    "auto": ("AUTO", "Automatic"),
    "nl": ("NL", "Dutch"),
    "en": ("EN", "English"),
    "de": ("DE", "German"),
    "es": ("ES", "Spanish"),
    "fr": ("FR", "French"),
    "zh": ("ZH", "Chinese (Mandarin)"),
}

saved_language = data.get("speech_language", "auto")

if saved_language not in SUPPORTED_SPEECH_LANGUAGES:
    saved_language = "auto"

speech_language_var = tk.StringVar(value=saved_language)

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


def apply_dark_title_bar():
    """Request a black Windows title bar with white caption text (Windows 11)."""
    try:
        if not hasattr(ctypes, "windll") or not root.winfo_exists():
            return

        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        if not hwnd:
            hwnd = root.winfo_id()

        dwmapi = ctypes.windll.dwmapi
        dwmapi.DwmSetWindowAttribute.argtypes = (
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint
        )
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long

        # Windows 11 DWM attributes: dark mode, caption colour and text colour.
        dark_mode = ctypes.c_int(1)
        black = ctypes.c_uint(0x00000000)
        white = ctypes.c_uint(0x00FFFFFF)

        for attribute in (20, 19):  # Attribute 20 on current Windows 11; 19 on older builds.
            result = dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), attribute,
                ctypes.byref(dark_mode), ctypes.sizeof(dark_mode)
            )
            if result == 0:
                break

        dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), 35, ctypes.byref(black), ctypes.sizeof(black)
        )
        dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), 36, ctypes.byref(white), ctypes.sizeof(white)
        )
        dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), 34, ctypes.byref(black), ctypes.sizeof(black)
        )
    except (AttributeError, OSError, tk.TclError, TypeError):
        # Unsupported Windows versions simply keep their normal title-bar theme.
        pass



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
        pygame.mixer.music.set_volume(1.0)
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
            current_text = editor.get("1.0", "end-1c")
            data["text"] = current_text  # Keep compatibility with older app versions.
            active_conversation = next(
                (item for item in conversations if item["id"] == active_conversation_id),
                None,
            )
            if active_conversation is not None:
                active_conversation["text"] = current_text

        data["conversations"] = conversations
        data["active_conversation_id"] = active_conversation_id
        data["sound_muted"] = sound_muted
        data["speech_language"] = speech_language_var.get()

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


def apply_native_topmost(window, enabled):
    """Keep a Tk window's native Windows Z-order flag in sync with On top."""
    try:
        if not window.winfo_exists():
            return

        window.update_idletasks()

        # winfo_id() can be the Tk client window; GetParent returns the
        # actual top-level Windows window that owns the Z-order.
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(window.winfo_id())
        if not hwnd:
            hwnd = window.winfo_id()

        from ctypes import wintypes

        user32.SetWindowPos.argtypes = (
            wintypes.HWND, wintypes.HWND,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_uint
        )
        user32.SetWindowPos.restype = wintypes.BOOL

        HWND_TOPMOST = wintypes.HWND(-1)
        HWND_NOTOPMOST = wintypes.HWND(-2)
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010

        insert_after = HWND_TOPMOST if enabled else HWND_NOTOPMOST
        user32.SetWindowPos(
            wintypes.HWND(hwnd),
            insert_after,
            0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
        )

    except (AttributeError, OSError, tk.TclError, TypeError):
        # Tk's own topmost attribute remains as a fallback.
        pass


def set_topmost():
    enabled = bool(top_var.get())
    root.attributes("-topmost", enabled)
    apply_native_topmost(root, enabled)

    if wolf is not None:
        try:
            if wolf.winfo_exists():
                wolf.attributes("-topmost", enabled)
                apply_native_topmost(wolf, enabled)
        except tk.TclError:
            pass

    if enabled:
        root.lift()

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
pin_button.pack(side="left", padx=(4, 0))


def maintain_topmost():
    pass
       

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

    started = speech_engine.start(language=speech_language_var.get())
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
speak_button.pack(side="left", padx=(2, 0))
def choose_speech_language():
    speech_engine.language = speech_language_var.get()
    save_data()
    update_language_button()


def update_language_button():
    code = speech_language_var.get()
    short_name = SUPPORTED_SPEECH_LANGUAGES[code][0]
    language_button.config(text=f"{short_name} ▼")


language_button = tk.Menubutton(
    header,
    text="EN ▼",
    bg="#252525",
    fg="white",
    activebackground="#3a3a3a",
    activeforeground="white",
    relief="flat",
    bd=0,
    font=("Segoe UI", 8),
    cursor="hand2",
    padx=5,
    pady=1,
)

language_menu = tk.Menu(
    language_button,
    tearoff=0,
    bg="#252525",
    fg="white",
    activebackground="#466080",
    activeforeground="white",
)

for code, (short_name, language_name) in SUPPORTED_SPEECH_LANGUAGES.items():
    language_menu.add_radiobutton(
        label=language_name,
        variable=speech_language_var,
        value=code,
        command=choose_speech_language,
    )

language_button.config(menu=language_menu)
language_button.pack(side="left", padx=(2, 0))

update_language_button()


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
sound_button.pack(side="left", padx=(2, 0))
update_sound_button()


# ============================================================
# NOTE EDITOR
# ============================================================

body = tk.Frame(root, bg=BG, padx=10, pady=10)
body.pack(fill="both", expand=True)

# Main writing area on the left; conversation tabs stay on the right.
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
# Narrow vertical sidebar for independent conversations. Pack it before
# the expanding editor so it always keeps its space on the right.
tabs_panel = tk.Frame(body, bg=PANEL, width=126, padx=5, pady=5)
tabs_panel.pack(side="right", fill="y", padx=(8, 0))
tabs_panel.pack_propagate(False)

tabs_heading = tk.Label(
    tabs_panel,
    text="CONVERSATIONS",
    bg=PANEL,
    fg=MUTED,
    font=("Segoe UI", 7, "bold"),
    anchor="w",
)
tabs_heading.pack(fill="x", pady=(2, 7))

tabs_canvas = tk.Canvas(tabs_panel, bg=PANEL, highlightthickness=0, bd=0)
# Keep a wide invisible hit area so the scrollbar is easy to grab, while
# drawing only a 2-pixel black line in its centre.
tabs_scrollbar = tk.Canvas(
    tabs_panel, width=10, bg=PANEL, highlightthickness=0, bd=0,
    cursor="arrow"
)
# Pack the New button first so the expanding canvas cannot consume its space.
# This keeps + New visible at the bottom of the sidebar.
tabs_list = tk.Frame(tabs_canvas, bg=PANEL)
tabs_window = tabs_canvas.create_window((0, 0), window=tabs_list, anchor="nw")

_scrollbar_drag = {"active": False, "grab_offset": 0}
_scrollbar_thumb = {"top": 0, "bottom": 0}

def update_tabs_scrollbar(first, last):
    """Draw a slim black thumb inside a wider, usable scrollbar hit area."""
    try:
        tabs_scrollbar.delete("thumb")
        height = tabs_scrollbar.winfo_height()
        width = tabs_scrollbar.winfo_width()
        if height <= 1 or width <= 1:
            return

        first = float(first)
        last = float(last)
        if first <= 0.0 and last >= 1.0:
            _scrollbar_thumb.update(top=0, bottom=height)
            return

        thumb_top = int(first * height)
        thumb_bottom = max(thumb_top + 18, int(last * height))
        thumb_bottom = min(height, thumb_bottom)
        _scrollbar_thumb.update(top=thumb_top, bottom=thumb_bottom)

        line_left = max(0, (width - 2) // 2)
        tabs_scrollbar.create_rectangle(
            line_left, thumb_top, line_left + 2, thumb_bottom,
            fill="#000000", outline="#000000", tags="thumb"
        )
    except (tk.TclError, ValueError):
        pass

def scroll_tabs_to_pointer(event, grab_offset=None):
    height = max(1, tabs_scrollbar.winfo_height())
    thumb_height = max(18, _scrollbar_thumb["bottom"] - _scrollbar_thumb["top"])
    max_top = max(0.0, 1.0 - (thumb_height / height))
    if grab_offset is None:
        grab_offset = thumb_height / 2
    desired_top = (event.y - grab_offset) / height
    tabs_canvas.yview_moveto(max(0.0, min(max_top, desired_top)))

def start_tabs_scrollbar_drag(event):
    top = _scrollbar_thumb["top"]
    bottom = _scrollbar_thumb["bottom"]
    if top <= event.y <= bottom:
        _scrollbar_drag["grab_offset"] = event.y - top
    else:
        # Clicking the track pages the thumb towards the clicked position.
        _scrollbar_drag["grab_offset"] = max(0, (bottom - top) / 2)
    _scrollbar_drag["active"] = True
    scroll_tabs_to_pointer(event, _scrollbar_drag["grab_offset"])

def drag_tabs_scrollbar(event):
    if _scrollbar_drag.get("active"):
        scroll_tabs_to_pointer(event, _scrollbar_drag["grab_offset"])

def stop_tabs_scrollbar_drag(event=None):
    _scrollbar_drag["active"] = False

def scroll_tabs_with_wheel(event):
    # The handler is global so it also works when the pointer is over a tab
    # button embedded inside the canvas; ignore the wheel everywhere else.
    try:
        px, py = event.x_root, event.y_root
        left = tabs_panel.winfo_rootx()
        top = tabs_panel.winfo_rooty()
        if not (left <= px < left + tabs_panel.winfo_width()
                and top <= py < top + tabs_panel.winfo_height()):
            return

        if getattr(event, "num", None) == 4:
            units = -3
        elif getattr(event, "num", None) == 5:
            units = 3
        else:
            delta = getattr(event, "delta", 0)
            if not delta:
                return
            units = -int(delta / 120) * 3
            if units == 0:
                units = -1 if delta > 0 else 1
        tabs_canvas.yview_scroll(units, "units")
        return "break"
    except tk.TclError:
        pass

tabs_scrollbar.bind("<Button-1>", start_tabs_scrollbar_drag)
tabs_scrollbar.bind("<B1-Motion>", drag_tabs_scrollbar)
tabs_scrollbar.bind("<ButtonRelease-1>", stop_tabs_scrollbar_drag)
tabs_canvas.configure(yscrollcommand=update_tabs_scrollbar)
tabs_list.bind(
    "<Configure>",
    lambda event: tabs_canvas.configure(scrollregion=tabs_canvas.bbox("all")),
)
tabs_canvas.bind(
    "<Configure>",
    lambda event: tabs_canvas.itemconfigure(tabs_window, width=event.width),
)
tabs_scrollbar.bind("<Configure>", lambda event: tabs_canvas.yview())
root.bind_all("<MouseWheel>", scroll_tabs_with_wheel, add="+")
root.bind_all("<Button-4>", scroll_tabs_with_wheel, add="+")
root.bind_all("<Button-5>", scroll_tabs_with_wheel, add="+")
new_tab_button = tk.Button(
    tabs_panel,
    text="+ New",
    command=lambda: create_conversation(),
    bg="#34465c",
    fg="white",
    activebackground="#466080",
    activeforeground="white",
    relief="flat",
    bd=0,
    cursor="hand2",
    font=("Segoe UI", 9, "bold"),
    padx=5,
    pady=5,
)
new_tab_button.pack(fill="x", pady=(6, 0))

# Pack the scrolling list after the fixed New button, reserving its space.
tabs_canvas.pack(side="left", fill="both", expand=True)
tabs_scrollbar.pack(side="right", fill="y", padx=(3, 0))

editor.pack(side="left", fill="both", expand=True)

# Restore the last active conversation. The legacy text field is used only
# as a fallback for data created by an older version of the app.
active_start = next(
    (item for item in conversations if item["id"] == active_conversation_id),
    conversations[0],
)
editor.insert("1.0", active_start.get("text", str(data.get("text", ""))))
editor.edit_modified(False)


def active_conversation():
    return next(
        (item for item in conversations if item["id"] == active_conversation_id),
        conversations[0] if conversations else None,
    )


def conversation_display_title(item):
    if item.get("custom_title") and item.get("title", "").strip():
        return item["title"].strip()

    first_line = next(
        (line.strip() for line in item.get("text", "").splitlines() if line.strip()),
        "",
    )
    if not first_line:
        return "New conversation"
    return first_line if len(first_line) <= 17 else first_line[:16].rstrip() + "…"


def sync_active_conversation():
    item = active_conversation()
    if item is not None:
        item["text"] = editor.get("1.0", "end-1c")


# Keep tab widgets alive between selections. Destroying and recreating every
# button on each click can expose a brief white native-window redraw on Windows.
conversation_tab_widgets = {}




# Drag-and-drop state for conversation tabs.
_tab_drag = {
    "conversation_id": None,
    "start_y": 0,
    "moved": False,
    "preview": None,
    "placeholder": None,
}


def clear_conversation_tab_drag_preview():
    for key in ("preview", "placeholder"):
        widget = _tab_drag.get(key)

        if widget is not None:
            try:
                widget.destroy()
            except tk.TclError:
                pass

        _tab_drag[key] = None


def start_conversation_tab_drag(event, conversation_id):
    clear_conversation_tab_drag_preview()

    _tab_drag["conversation_id"] = conversation_id
    _tab_drag["start_y"] = event.y_root
    _tab_drag["moved"] = False


def move_conversation_tab_drag(event, conversation_id):
    if _tab_drag["conversation_id"] != conversation_id:
        return

    if abs(event.y_root - _tab_drag["start_y"]) < 6:
        return

    _tab_drag["moved"] = True

    # Create a placeholder where the original tab was.
    if _tab_drag["placeholder"] is None:
        dragged_row = conversation_tab_widgets[conversation_id]["row"]

        tabs_list.update_idletasks()

        row_height = max(dragged_row.winfo_height(), 1)
        siblings = tabs_list.pack_slaves()
        row_index = siblings.index(dragged_row)

        next_widget = (
            siblings[row_index + 1]
            if row_index + 1 < len(siblings)
            else None
        )

        dragged_row.pack_forget()

        placeholder = tk.Frame(
            tabs_list,
            height=row_height,
            bg="#34383b",
            relief="ridge",
            bd=1,
        )
        placeholder.pack_propagate(False)

        if next_widget is not None:
            placeholder.pack(fill="x", pady=2, before=next_widget)
        else:
            placeholder.pack(fill="x", pady=2)

        _tab_drag["placeholder"] = placeholder
        tabs_list.update_idletasks()

    # Create the floating conversation-name preview.
    if _tab_drag["preview"] is None:
        item = next(
            (entry for entry in conversations if entry["id"] == conversation_id),
            None,
        )

        if item is None:
            return

        preview = tk.Toplevel(root)
        preview.overrideredirect(True)
        preview.attributes("-topmost", True)
        preview.configure(bg="#4a4d50")

        label = tk.Label(
            preview,
            text=conversation_display_title(item),
            bg="#4a4d50",
            fg="#ffffff",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=7,
            relief="solid",
            bd=1,
        )
        label.pack()

        _tab_drag["preview"] = preview

    # Keep the preview centered above the mouse cursor.
    preview = _tab_drag["preview"]
    preview.update_idletasks()

    preview_x = event.x_root - preview.winfo_width() // 2
    preview_y = event.y_root - preview.winfo_height() - 12

    preview.geometry(f"+{preview_x}+{preview_y}")

    # Move the placeholder between the remaining conversation tabs.
    remaining_items = [
        item for item in conversations
        if item["id"] != conversation_id
    ]

    placeholder = _tab_drag["placeholder"]

    tabs_list.update_idletasks()

    insert_index = len(remaining_items)

    for index, item in enumerate(remaining_items):
        row = conversation_tab_widgets[item["id"]]["row"]
        row_middle = row.winfo_rooty() + row.winfo_height() / 2

        if event.y_root < row_middle:
            insert_index = index
            placeholder.pack_configure(before=row)
            break

    else:
        if remaining_items:
            last_row = conversation_tab_widgets[
                remaining_items[-1]["id"]
            ]["row"]

            placeholder.pack_configure(after=last_row)

    tabs_list.update_idletasks()


    


def finish_conversation_tab_drag(event, conversation_id):
    if _tab_drag["conversation_id"] != conversation_id:
        return

    if not _tab_drag["moved"]:
        clear_conversation_tab_drag_preview()
        _tab_drag["conversation_id"] = None
        return

    dragged_item = next(
        (item for item in conversations if item["id"] == conversation_id),
        None,
    )

    if dragged_item is None:
        clear_conversation_tab_drag_preview()
        _tab_drag["conversation_id"] = None
        _tab_drag["moved"] = False
        return "break"

    remaining_items = [
        item for item in conversations
        if item["id"] != conversation_id
    ]

    insert_index = len(remaining_items)

    for index, item in enumerate(remaining_items):
        row = conversation_tab_widgets[item["id"]]["row"]
        row_middle = row.winfo_rooty() + row.winfo_height() / 2

        if event.y_root < row_middle:
            insert_index = index
            break

    remaining_items.insert(insert_index, dragged_item)
    conversations[:] = remaining_items

    clear_conversation_tab_drag_preview()
    _tab_drag["conversation_id"] = None
    _tab_drag["moved"] = False

    refresh_conversation_tabs()
    save_data()

    return "break"



# Available conversation tab colours.
TAB_COLORS = {
    "Red": "#B83232",
    "Orange": "#C45D16",
    "Yellow": "#9A8310",
    "Green": "#25834A",
    "Blue": "#2469B5",
    "Purple": "#7542B8",
    "Pink": "#B83F78",
}


def set_conversation_tab_color(conversation_id, color):
    item = next(
        (entry for entry in conversations if entry["id"] == conversation_id),
        None,
    )

    if item is None:
        return

    if color is None:
        item.pop("tab_color", None)
    else:
        item["tab_color"] = color

    refresh_conversation_tabs()
    save_data()


def show_conversation_tab_color_menu(event, conversation_id):
    menu = tk.Menu(root, tearoff=0)

    menu.add_command(
        label="No colour",
        command=lambda: set_conversation_tab_color(conversation_id, None),
    )

    menu.add_separator()

    for name, color in TAB_COLORS.items():
        menu.add_command(
            label=name,
            command=lambda c=color: set_conversation_tab_color(
                conversation_id, c
            ),
        )

    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()

    return "break"

def refresh_conversation_tabs():
    global _last_tab_title

    active_item = active_conversation()
    _last_tab_title = conversation_display_title(active_item) if active_item else None
    current_ids = {item["id"] for item in conversations}

    # Remove only tabs that were actually deleted.
    for conversation_id in list(conversation_tab_widgets):
        if conversation_id not in current_ids:
            widgets = conversation_tab_widgets.pop(conversation_id)
            widgets["row"].destroy()

    # Create missing tabs once, then update their appearance and text.
    for item in conversations:
        conversation_id = item["id"]
        widgets = conversation_tab_widgets.get(conversation_id)

        if widgets is None:
            tab_row = tk.Frame(tabs_list, bg=PANEL)
            tab_row.pack(fill="x", pady=2)

            tab_button = tk.Button(
                tab_row,
                command=lambda cid=conversation_id: switch_conversation(cid),
                activebackground="#4a4d50",
                activeforeground="white",
                relief="flat",
                bd=0,
                highlightthickness=0,
                takefocus=0,
                default="normal",
                anchor="w",
                justify="left",
                cursor="hand2",
                padx=5,
                pady=6,
            )

            
            tab_button.bind(
                "<Double-Button-1>",
                lambda event, cid=conversation_id: rename_conversation(cid),
            )
            tab_button.bind(
                "<Button-3>",
                lambda event, cid=conversation_id: show_conversation_tab_color_menu(
                    event, cid
                ),
            )
            tab_button.bind(
                "<Button-1>",
                lambda event, cid=conversation_id: start_conversation_tab_drag(event, cid),
                add="+",
            )
            tab_button.bind(
                "<B1-Motion>",
                lambda event, cid=conversation_id: move_conversation_tab_drag(event, cid),
                add="+",
            )
            tab_button.bind(
                "<ButtonRelease-1>",
                lambda event, cid=conversation_id: finish_conversation_tab_drag(event, cid),
                add="+",
            )


            close_button = tk.Button(
                tab_row,
                text="×",
                command=lambda cid=conversation_id: remove_conversation(cid),
                fg="#ff5c5c",
                activebackground="#5a3030",
                activeforeground="#ff7777",
                relief="flat",
                bd=0,
                highlightthickness=0,
                takefocus=0,
                default="normal",
                cursor="hand2",
                font=("Segoe UI", 11, "bold"),
                padx=5,
                pady=1,
            )
            
            close_button.pack(side="right", padx=(0, 3), ipadx=2)
            tab_button.pack(side="left", fill="x", expand=True)
            widgets = {
                "row": tab_row,
                "button": tab_button,
                "close": close_button,
            }
            conversation_tab_widgets[conversation_id] = widgets

        
        selected = conversation_id == active_conversation_id
        tab_color = item.get("tab_color")


        if tab_color:
            background = tab_color
        else:
            background = "#3c4043" if selected else PANEL

        widgets["row"].configure(bg=background)
        widgets["button"].configure(
            text=conversation_display_title(item),
            bg=background,
            fg="#ffffff" if selected or tab_color else TEXT,
            activebackground=background,
            activeforeground="#ffffff",
            font=("Segoe UI", 8, "bold" if selected else "normal"),
        )
        widgets["close"].configure(bg=background)



    # Reorder the existing tab rows to match the conversations list.
    for item in conversations:
        conversation_tab_widgets[item["id"]]["row"].pack_forget()

    for item in conversations:
        conversation_tab_widgets[item["id"]]["row"].pack(fill="x", pady=2)



def switch_conversation(conversation_id):
    global active_conversation_id, _last_editor_text

    if conversation_id == active_conversation_id:
        return

    sync_active_conversation()
    target = next((item for item in conversations if item["id"] == conversation_id), None)
    if target is None:
        return

    active_conversation_id = conversation_id
    editor.delete("1.0", "end")
    editor.insert("1.0", target.get("text", ""))
    editor.edit_modified(False)
    _last_editor_text = editor.get("1.0", "end-1c")
    refresh_conversation_tabs()
    save_data()
    editor.focus_set()


def create_conversation():
    global active_conversation_id, _last_editor_text

    sync_active_conversation()
    item = {
        "id": uuid.uuid4().hex,
        "title": "New conversation",
        "custom_title": False,
        "text": "",
    }
    conversations.insert(0, item)
    active_conversation_id = item["id"]
    editor.delete("1.0", "end")
    editor.edit_modified(False)
    _last_editor_text = ""
    refresh_conversation_tabs()
    save_data()
    editor.focus_set()


def rename_conversation(conversation_id):
    item = next((entry for entry in conversations if entry["id"] == conversation_id), None)
    if item is None:
        return

    current_name = conversation_display_title(item)
    new_name = simpledialog.askstring(
        "Rename conversation",
        "Enter a name for this conversation:",
        initialvalue=current_name,
        parent=root,
    )
    if new_name is None:
        return

    new_name = new_name.strip()
    if not new_name:
        messagebox.showinfo("Rename conversation", "The conversation name cannot be empty.", parent=root)
        return

    item["title"] = new_name
    item["custom_title"] = True
    refresh_conversation_tabs()
    save_data()


def ask_remove_confirmation(conversation_title):
    """Show a custom dark confirmation dialog instead of Windows' grey message box."""
    dialog = tk.Toplevel(root)
    dialog.title("Remove conversation")
    dialog.configure(bg=BG)
    dialog.resizable(False, False)
    dialog.transient(root)

    result = {"confirmed": False}

    outer = tk.Frame(dialog, bg=BG, padx=22, pady=18)
    outer.pack(fill="both", expand=True)

    tk.Label(
        outer,
        text="Remove this conversation?",
        bg=BG,
        fg=TEXT,
        font=("Segoe UI", 11),
        anchor="w",
    ).pack(fill="x", pady=(0, 9))

    tk.Label(
        outer,
        text=f'Are you sure you want to remove "{conversation_title}" and all its saved text?',
        bg=BG,
        fg=TEXT,
        font=("Segoe UI", 9),
        justify="left",
        wraplength=340,
        anchor="w",
    ).pack(fill="x", pady=(0, 18))

    button_row = tk.Frame(outer, bg=BG)
    button_row.pack(fill="x")

    def close_dialog(confirmed=False):
        result["confirmed"] = confirmed
        try:
            dialog.grab_release()
        except tk.TclError:
            pass
        dialog.destroy()

    tk.Button(
        button_row,
        text="Cancel",
        command=lambda: close_dialog(False),
        bg=PANEL,
        fg=TEXT,
        activebackground=BORDER,
        activeforeground=TEXT,
        relief="flat",
        bd=0,
        padx=16,
        pady=7,
        cursor="hand2",
        takefocus=False,
    ).pack(side="right", padx=(8, 0))

    tk.Button(
        button_row,
        text="Remove",
        command=lambda: close_dialog(True),
        bg="#8b2525",
        fg="#ffffff",
        activebackground="#a83232",
        activeforeground="#ffffff",
        relief="flat",
        bd=0,
        padx=16,
        pady=7,
        cursor="hand2",
        takefocus=False,
    ).pack(side="right")

    dialog.bind("<Escape>", lambda event: close_dialog(False))
    dialog.protocol("WM_DELETE_WINDOW", lambda: close_dialog(False))
    dialog.update_idletasks()

    # Centre the dialog over the main window.
    width = dialog.winfo_reqwidth()
    height = dialog.winfo_reqheight()
    x = root.winfo_rootx() + max(0, (root.winfo_width() - width) // 2)
    y = root.winfo_rooty() + max(0, (root.winfo_height() - height) // 2)
    dialog.geometry(f"{width}x{height}+{x}+{y}")

    # Match the black Windows title bar used by the main app.
    try:
        hwnd = dialog.winfo_id()
        dwmapi = ctypes.windll.dwmapi
        dwmapi.DwmSetWindowAttribute.argtypes = (
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint
        )
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
        dark_mode = ctypes.c_int(1)
        black = ctypes.c_uint(0x00000000)
        white = ctypes.c_uint(0x00FFFFFF)
        for attribute in (20, 19):
            if dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), attribute,
                ctypes.byref(dark_mode), ctypes.sizeof(dark_mode)
            ) == 0:
                break
        for attribute, colour in ((35, black), (36, white), (34, black)):
            dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), attribute,
                ctypes.byref(colour), ctypes.sizeof(colour)
            )
    except (AttributeError, OSError, tk.TclError, TypeError):
        pass

    dialog.grab_set()
    dialog.focus_force()
    dialog.wait_window()
    return result["confirmed"]


def remove_conversation(conversation_id):
    global active_conversation_id, _last_editor_text

    if conversation_id == active_conversation_id:
        sync_active_conversation()

    item = next((entry for entry in conversations if entry["id"] == conversation_id), None)
    if item is None:
        return

    if item.get("text", "").strip():
        confirmed = ask_remove_confirmation(conversation_display_title(item))
        if not confirmed:
            return

    removed_index = conversations.index(item)
    was_active = conversation_id == active_conversation_id
    conversations.remove(item)

    if not conversations:
        replacement = {
            "id": uuid.uuid4().hex,
            "title": "New conversation",
            "custom_title": False,
            "text": "",
        }
        conversations.append(replacement)

    if was_active:
        next_index = min(removed_index, len(conversations) - 1)
        target = conversations[next_index]
        active_conversation_id = target["id"]
        editor.delete("1.0", "end")
        editor.insert("1.0", target.get("text", ""))
        editor.edit_modified(False)
        _last_editor_text = editor.get("1.0", "end-1c")

    refresh_conversation_tabs()
    save_data()
    if was_active:
        editor.focus_set()


refresh_conversation_tabs()


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
    wolf.attributes("-topmost", bool(top_var.get()))
    apply_native_topmost(wolf, bool(top_var.get()))

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

            # Reapply the Windows setting that hides the wolf's taskbar button.
            try:
                wolf.update_idletasks()

                user32 = ctypes.windll.user32
                hwnd = user32.GetParent(wolf.winfo_id())

                if not hwnd:
                    hwnd = wolf.winfo_id()

                GWL_EXSTYLE = -20
                WS_EX_TOOLWINDOW = 0x00000080
                WS_EX_APPWINDOW = 0x00040000

                style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

                user32.SetWindowLongW(
                    hwnd,
                    GWL_EXSTYLE,
                    (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW,
                )

                user32.SetWindowPos(
                    hwnd,
                    0,
                    0, 0, 0, 0,
                    0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020,
                )

            except (AttributeError, OSError, tk.TclError):
                pass

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
    root.after(50, set_topmost)
    root.after(100, apply_dark_title_bar)
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
fold_button.pack(side="left")

# Set the header controls in the exact requested left-to-right order.
# Repacking them here avoids their earlier creation order affecting layout.
for header_control in (fold_button, sound_button, speak_button, language_button, pin_button):
    header_control.pack_forget()

fold_button.pack(side="left", padx=(0, 2))
sound_button.pack(side="left", padx=(2, 0))
speak_button.pack(side="left", padx=(2, 0))
language_button.pack(side="left", padx=(2, 0))
pin_button.pack(side="left", padx=(4, 0))


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
            item = active_conversation()
            if item is not None:
                item["text"] = current_text
                current_title = conversation_display_title(item)
                if current_title != _last_tab_title and not item.get("custom_title"):
                    refresh_conversation_tabs()
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

    def hide_initial_wolf_from_taskbar():
        try:
            if wolf is None or not wolf.winfo_exists():
                return

            wolf.update_idletasks()

            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(wolf.winfo_id())

            if not hwnd:
                hwnd = wolf.winfo_id()

            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000

            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

            user32.SetWindowLongW(
                hwnd,
                GWL_EXSTYLE,
                (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW,
            )

            user32.SetWindowPos(
                hwnd,
                0,
                0, 0, 0, 0,
                0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020,
            )

        except (AttributeError, OSError, tk.TclError):
            pass

    root.after(300, hide_initial_wolf_from_taskbar)


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
root.after(2000, maintain_topmost)

root.withdraw()
root.after(500, start_compact_silently)

root.mainloop()
