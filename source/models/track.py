from dataclasses import dataclass, field
from source.services.camelot import parse_camelot


@dataclass
class Track:
    file_name: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    bpm: float = 0.0
    key: str = ""
    camelot_key: str = ""
    camelot_number: int = 0
    camelot_letter: str = ""
    genre: str = ""
    date: str = ""
    comments: str = ""
    energy: int = 0
    play_count: int = 0
    date_added: float = 0.0  # file creation time (Unix timestamp), read fresh each sync; 0.0 = unknown. See ADR-013.
    full_file_path: str = ""
    crates: list[str] = field(default_factory=list)  # crate ids (ADR-015 D3)
    sources: tuple[str, ...] = ()  # provider ids holding this file, precedence order (D6)
    search_text: str = ""

    @classmethod
    def from_dict(cls, data: dict, file_path: str = "") -> "Track":
        """Create a Track from a library snapshot track dict (JSON-sourced).

        Numeric fields are already their native types; values are coerced defensively.
        """
        bpm = 0.0
        try:
            bpm = float(data.get("bpm", 0))
        except (ValueError, TypeError):
            pass

        play_count = 0
        try:
            play_count = int(data.get("play_count", 0))
        except (ValueError, TypeError):
            pass

        # date_added: file creation time (Unix float), read fresh each sync;
        # 0.0 = unknown. Mirrors the bpm coercion. See ADR-013.
        date_added = 0.0
        try:
            date_added = float(data.get("date_added", 0.0) or 0.0)
        except (ValueError, TypeError):
            pass

        camelot_key = (data.get("camelot_key", "") or "").strip()

        # Energy from tag value
        energy = 0
        try:
            energy = int(data.get("energy_level", 0))
        except (ValueError, TypeError):
            pass

        camelot_number = 0
        camelot_letter = ""
        parsed = parse_camelot(camelot_key)
        if parsed:
            camelot_number, camelot_letter = parsed

        title = data.get("title", "") or ""
        artist = data.get("artist", "") or ""
        file_name = data.get("file_name", "") or ""
        full_path = data.get("full_file_path", file_path) or file_path

        crates = list(data.get("crates", []))
        sources = tuple(data.get("sources", ()))  # set by library_merge; never stored
        search_text = f"{title} {artist} {file_name}".lower()

        return cls(
            file_name=file_name,
            title=title,
            artist=artist,
            album=data.get("album", "") or "",
            bpm=bpm,
            key=data.get("key", "") or "",
            camelot_key=camelot_key,
            camelot_number=camelot_number,
            camelot_letter=camelot_letter,
            genre=data.get("genre", "") or "",
            date=data.get("date", "") or "",
            comments=data.get("comments", "") or "",
            energy=energy,
            play_count=play_count,
            date_added=date_added,
            full_file_path=full_path,
            crates=crates,
            sources=sources,
            search_text=search_text,
        )

    @property
    def display_name(self) -> str:
        if self.artist and self.title:
            return f"{self.artist} - {self.title}"
        return self.title or self.file_name
