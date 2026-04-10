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
    full_file_path: str = ""
    crates: list = field(default_factory=list)
    search_text: str = ""

    @classmethod
    def from_csv_row(cls, row: dict, crate_name: str = "") -> "Track":
        """Create a Track from a CSV row dict."""
        # Parse BPM
        bpm = 0.0
        try:
            bpm = float(row.get("BPM", "") or "0")
        except ValueError:
            pass

        # Parse play count
        play_count = 0
        try:
            play_count = int(row.get("PlayCount", "") or "0")
        except ValueError:
            pass

        # Get Camelot key from CSV column
        camelot_key = (row.get("CamelotKey", "") or "").strip()

        # Energy from CSV column
        energy = 0
        energy_str = (row.get("EnergyLevel", "") or "").strip()
        if energy_str:
            try:
                energy = int(energy_str)
            except ValueError:
                pass

        # Parse Camelot into number/letter
        camelot_number = 0
        camelot_letter = ""
        parsed = parse_camelot(camelot_key)
        if parsed:
            camelot_number, camelot_letter = parsed

        title = row.get("Title", "") or ""
        artist = row.get("Artist", "") or ""
        file_name = row.get("FileName", "") or ""

        crates = [crate_name] if crate_name else []

        search_text = f"{title} {artist} {file_name}".lower()

        return cls(
            file_name=file_name,
            title=title,
            artist=artist,
            album=row.get("Album", "") or "",
            bpm=bpm,
            key=row.get("Key", "") or "",
            camelot_key=camelot_key,
            camelot_number=camelot_number,
            camelot_letter=camelot_letter,
            genre=row.get("Genre", "") or "",
            date=row.get("Date", "") or "",
            comments=row.get("Comments", "") or "",
            energy=energy,
            play_count=play_count,
            full_file_path=row.get("FullFilePath", "") or "",
            crates=crates,
            search_text=search_text,
        )

    @classmethod
    def from_dict(cls, data: dict, file_path: str = "") -> "Track":
        """Create a Track from a cache dict entry (JSON-sourced).

        Unlike from_csv_row(), numeric fields are already their native types.
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
            full_file_path=full_path,
            crates=crates,
            search_text=search_text,
        )

    @property
    def display_name(self) -> str:
        if self.artist and self.title:
            return f"{self.artist} - {self.title}"
        return self.title or self.file_name
