import logging

import customtkinter as ctk
from source.app import DJTrackSelectorApp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = DJTrackSelectorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
