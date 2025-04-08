import logging
import json
import enum
import pydub
import pynput
import queue
import threading
import pygame
import io
from ttkbootstrap import Window
from tkinter import ttk, StringVar

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(filename="keyboard.log", level=logging.INFO)
logger.info("-----------start-app-----------")


class EnumKeys(enum.Enum):
    id = "id"
    name = "name"
    key_define_type = "key_define_type"
    sound = "sound"
    defines = "defines"


class Configs:
    config_file_name = "sound_config.json"

    def __init__(self):
        self.errors = []
        self.configs = self.load_config()
        if self.configs is None:
            logger.error("[e] Unable to load configs.")
        else:
            logger.info("[*] All configs loaded successfully.")

    def __getattribute__(self, name):
        if name in EnumKeys.__members__:
            return self.get(name)
        try:
            return super().__getattribute__(name)
        except AttributeError:
            raise AttributeError(f"There is no attribute named: {name}")

    def get(self, key, default=None):
        if isinstance(key, str):
            key = EnumKeys[key]
        try:
            return self.configs[key.name]
        except KeyError:
            self.errors.append(
                f"KeyError: Expected key not found in JSON file. [filename: {self.config_file_name}]"
            )
            return default

    def load_config(self):
        try:
            with open(self.config_file_name, "r") as file:
                result = json.loads(file.read())
                logger.info("[*] Config file loaded.")
                return result
        except FileNotFoundError:
            self.errors.append(
                f"File does not exist. [filename: {self.config_file_name}]"
            )
        except json.JSONDecodeError:
            self.errors.append("JSON decode error.")
        logger.error("[e] Can't load config file.")
        return None


class SoundLoaderThread(threading.Thread):
    def __init__(self, config, callback):
        super().__init__()
        self.config = config
        self.callback = callback
        self.daemon = True

    def run(self):
        try:
            sound_path = self.config.get("sound")
            sound = pydub.AudioSegment.from_file(sound_path)
            logger.info("[*] Sound file loaded in background.")
            self.callback(sound)
        except Exception as e:
            logger.error(f"[e] Failed to load sound file: {e}")
            self.callback(None)


class Sound:
    def __init__(self, config, sound_segment=None):
        pygame.mixer.init()
        self.config = config
        self.sound = sound_segment
        self.sound_effect = {}
        self.queue_for_play = queue.Queue()
        self.number_of_sounds = 10
        self.running = True
        self.loading = True
        self.volume = 1.0  # Default volume (max)
        self.special_chars = {key: idx for idx, key in enumerate(pynput.keyboard.Key)}
        if self.sound:
            self.load_all_sounds()

    def slice_sound(self, start_time, duration_time):
        sound_slice = self.sound[start_time : (start_time + duration_time)]
        data = io.BytesIO()
        sound_slice.export(data, format="ogg")
        data.seek(0)
        sound_obj = pygame.mixer.Sound(data)
        sound_obj.set_volume(self.volume)
        return sound_obj

    def start_threads(self):
        self.running = True
        threading.Thread(
            target=self.thread_worker_player, name="player", daemon=True
        ).start()

    def stop_threads(self):
        self.running = False
        self.queue_for_play.put((None, None))

    @property
    def is_loaded(self):
        return not self.loading

    def load_all_sounds(self):
        try:
            defines = self.config.get("defines")
            for i in range(1, self.number_of_sounds + 1):
                start, duration = defines[str(i)]
                self.sound_effect[str(i)] = self.slice_sound(start, duration)
                start_up, duration_up = defines[f"{i}-up"]
                self.sound_effect[f"{i}-up"] = self.slice_sound(start_up, duration_up)
            self.loading = False
            logger.info("[*] All sound effects loaded.")
        except Exception as e:
            logger.error(f"[e] Error loading sounds: {e}")
            self.loading = False

    def update_volume(self, new_volume):
        """Update the volume of all loaded sound effects."""
        self.volume = new_volume
        for sound in self.sound_effect.values():
            sound.set_volume(self.volume)
        logger.info(f"Volume set to {self.volume}")

    def play_sound(self, key, release=False):
        try:
            sound_index = int(ord(key.char)) % self.number_of_sounds
        except Exception:
            sound_index = self.special_chars.get(key, 0) % self.number_of_sounds
        sound_index = f"{sound_index}-up" if release else str(sound_index)
        expected_sound = self.sound_effect.get(sound_index)
        if expected_sound:
            expected_sound.play()
        else:
            logger.warning(f"No sound effect found for key index: {sound_index}")

    def thread_worker_player(self):
        while self.running:
            try:
                key, release = self.queue_for_play.get(timeout=0.5)
                if key is None and release is None:
                    continue
                threading.Thread(
                    target=self.play_sound,
                    args=(key, release),
                    name="player-sound",
                    daemon=True,
                ).start()
            except queue.Empty:
                continue


class Keyboard(Sound):
    def __init__(self, parent, config):
        self.parent = parent
        super().__init__(config, sound_segment=None)
        self.is_keyboard_on = False
        self.keyboard_listener = None

    def set_sound(self, sound_segment):
        self.sound = sound_segment
        self.load_all_sounds()
        # Apply the current volume to newly loaded sounds
        self.update_volume(self.volume)

    def on_press(self, key):
        self.parent.update_status(f"Pressed: {key}")
        self.queue_for_play.put((key, False))

    def on_release(self, key):
        self.queue_for_play.put((key, True))

    def stop(self):
        if self.keyboard_listener:
            self.keyboard_listener.stop()
        self.stop_threads()

    def start(self):
        self.listen()
        self.start_threads()

    def listen(self):
        self.keyboard_listener = pynput.keyboard.Listener(
            on_press=self.on_press, on_release=self.on_release
        )
        self.keyboard_listener.start()


class MainWindow(Window):
    def __init__(self):
        super().__init__(themename="darkly")
        self.title("Keyboard Sound App")
        self.geometry("400x250")
        self.resizable(False, False)

        # Access the existing style
        style = self.style

        # Configure styles
        style.configure("TLabel", font=("Helvetica", 12))
        style.configure("TButton", font=("Helvetica", 12), padding=6)

        # Main container
        self.main_frame = ttk.Frame(self)
        self.main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Status label
        self.status_text = StringVar(value="Loading sound...")
        self.status_label = ttk.Label(
            self.main_frame, textvariable=self.status_text, anchor="center"
        )
        self.status_label.pack(fill="x", pady=10)

        # Toggle button for keyboard listening
        self.toggle_btn = ttk.Button(
            self.main_frame,
            text="Start",
            command=self.change_state,
            style="primary.TButton",
        )
        self.toggle_btn.pack(fill="x", pady=10)

        # Volume control label and slider
        self.volume_label = ttk.Label(self.main_frame, text="Volume:")
        self.volume_label.pack(fill="x", pady=(10, 0))
        self.volume_slider = ttk.Scale(
            self.main_frame,
            from_=0,
            to=100,
            orient="horizontal",
            command=self.on_volume_change,
        )
        self.volume_slider.set(100)  # Default to max volume
        self.volume_slider.pack(fill="x", pady=(0, 10))

        # Load configuration and create a keyboard instance stored as a "private" attribute.
        self.config = Configs()
        self._sound_keyboard = Keyboard(self, self.config)

        # Start loading sound
        self.start_sound_loading()

    def start_sound_loading(self):
        SoundLoaderThread(self.config, self.sound_loaded).start()

    def sound_loaded(self, sound_segment):
        if sound_segment:
            self._sound_keyboard.set_sound(sound_segment)
            self.status_text.set("Sound loaded. Press Start.")
        else:
            self.status_text.set("Error loading sound!")
            self.toggle_btn.config(state="disabled")

    def update_status(self, message):
        self.status_text.set(message)

    def change_state(self):
        if self._sound_keyboard.is_keyboard_on:
            self._sound_keyboard.stop()
            self._sound_keyboard.is_keyboard_on = False
            self.toggle_btn.config(text="Start")
            self.status_text.set("Keyboard stopped")
        else:
            if not self._sound_keyboard.is_loaded:
                self.status_text.set("Still loading sound, please wait...")
                return
            self._sound_keyboard.start()
            self._sound_keyboard.is_keyboard_on = True
            self.toggle_btn.config(text="Stop")
            self.status_text.set("Keyboard running...")

    def on_volume_change(self, value):
        """Callback to update volume from slider changes."""
        new_volume = float(value) / 100.0  # Convert 0-100 to 0.0-1.0 scale
        self._sound_keyboard.update_volume(new_volume)
        self.update_status(f"Volume set to {int(float(value))}%")

    def on_closing(self):
        self._sound_keyboard.stop()
        self.destroy()


if __name__ == "__main__":
    app = MainWindow()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
