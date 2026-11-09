"""Import a private, byte-preserving audio bundle from the Ducky source export.

HTML/JavaScript is treated as data: only JSON5 literals are parsed. No source
script is executed and no speech is synthesized. Requires ffprobe on PATH.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import json5

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_MEMBERS = 2048
ROOT = "duck-export/"
_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("Unsafe audio identifier")
    return value


def _archive_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS or sum(i.file_size for i in infos) > MAX_TOTAL_BYTES:
        raise ValueError("Archive exceeds size limit")
    result = {}
    for item in infos:
        name = item.filename
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in name
            or ":" in name
            or "\x00" in name
            or stat.S_ISLNK(item.external_attr >> 16)
        ):
            raise ValueError(f"Unsafe archive member: {name!r}")
        if name in result:
            raise ValueError(f"Duplicate archive member: {name}")
        if item.file_size > MAX_MEMBER_BYTES:
            raise ValueError(f"Archive member exceeds size limit: {name}")
        result[name] = item
    return result


def _read(archive: zipfile.ZipFile, members: dict, name: str) -> bytes:
    if name not in members:
        raise ValueError(f"Missing source member: {name}")
    with archive.open(members[name]) as stream:
        data = stream.read(MAX_MEMBER_BYTES + 1)
    if len(data) > MAX_MEMBER_BYTES:
        raise ValueError(f"Member exceeds read limit: {name}")
    return data


def _literal(html: str, name: str, required: bool = True) -> list:
    """Find variable declarations, parse literal values, and reject executable RHS."""
    matches = list(
        re.finditer(r"\b(?:var|let|const)\s+" + re.escape(name) + r"\s*=", html)
    )
    if required and len(matches) != 1:
        raise ValueError(f"Expected one {name} source declaration")
    values = []
    for match in matches:
        value, error, end = json5.parse(
            html, start=match.end(), consume_trailing=False, allow_duplicate_keys=False
        )
        if error or not html[end:].lstrip().startswith(";"):
            raise ValueError(f"Malformed JSON5 literal: {name}")
        values.append(value)
    return values


def _static_speech(html: str):
    """Read entirely literal say/sayPair arguments; never evaluate callbacks.

    A call containing even one expression is ignored as a whole. Parsing each
    string through JSON5 also handles escaped quotes without interpreting JS.
    """
    for match in re.finditer(r"\b(sayPair|say)\s*\(", html):
        position = match.end()
        arguments = []
        complete = False
        for _ in range(4):
            value, error, end = json5.parse(
                html, start=position, consume_trailing=False, allow_duplicate_keys=False
            )
            if error or not isinstance(value, str):
                break
            arguments.append(value)
            position = end
            while position < len(html) and html[position].isspace():
                position += 1
            if position >= len(html):
                break
            if html[position] == ")":
                complete = True
                break
            if html[position] != ",":
                break
            position += 1
        if not complete:
            continue
        if match[1] == "sayPair" and len(arguments) == 4:
            yield arguments[0], arguments[1]
            yield arguments[2], arguments[3]
        elif match[1] == "say" and 2 <= len(arguments) <= 4:
            yield arguments[0], arguments[1]


def _source_metadata(html: str, archive: zipfile.ZipFile, members: dict) -> dict:
    metadata: dict[str, dict] = {}

    def add(identifier, group, *, label=None, text=None):
        identifier = _identifier(identifier)
        record = metadata.setdefault(identifier, {})
        record.update(group=group)
        if label is not None:
            if not isinstance(label, str):
                raise ValueError("Invalid audio label")
            record["label"] = label
        if text is not None:
            if not isinstance(text, str) or not text.strip():
                raise ValueError("Invalid source transcript")
            record.update(text=text, text_source="space.html")

    try:
        scenes = _literal(html, "SCENES")[0]
        for group, scene in scenes.items():
            greeting = scene.get("greeting")
            if greeting:
                add(greeting["id"], group, text=greeting["text"])
            for word in scene.get("words", []):
                add(word[0], group, label=word[1])
            for sentence in scene.get("sentences", []):
                add(sentence[0], group, text=sentence[1])
        for group, entries in _literal(html, "GOODBYES")[0].items():
            for identifier, transcript in entries:
                add(identifier, group, text=transcript)
        for group, entry in _literal(html, "SCENE_ACTIONS")[0].items():
            add(entry["id"], group, label=entry.get("label"), text=entry["text"])
        for pack in _literal(html, "REVIEW_PACKS")[0]:
            group = pack["id"]
            intro = pack.get("intro")
            if intro:
                add(intro["id"], group, text=intro["text"])
            for scene in pack.get("scenes", []):
                for word in scene.get("words", []):
                    add(word["audio"], group, label=word["word"])
            for phrase in pack.get("phrases", []):
                add(
                    phrase["audio"],
                    group,
                    label=phrase.get("label"),
                    text=phrase["text"],
                )
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError("Malformed page audio metadata") from exc

    transcripts = {}
    for filename in ["clips.tsv", "new_clips.tsv", "tide-lines.tsv", "why-lines.tsv"]:
        member = ROOT + "lines/" + filename
        if member not in members:
            continue
        for line in _read(archive, members, member).decode("utf-8-sig").splitlines():
            if not line.strip():
                continue
            columns = line.split("\t", 1)
            if len(columns) != 2 or not columns[1].strip():
                raise ValueError(f"Malformed transcript in {member}")
            identifier = _identifier(columns[0].removesuffix(".mp3"))
            if identifier in transcripts and transcripts[identifier] != columns[1]:
                raise ValueError(f"Conflicting source transcripts: {identifier}")
            transcripts[identifier] = columns[1]
            record = metadata.setdefault(identifier, {})
            # TSV contains spoken word phrases; the page often holds only a label.
            record.setdefault("text", columns[1])
            record.setdefault("text_source", member)
    for identifier, transcript in _static_speech(html):
        identifier = _identifier(identifier)
        record = metadata.setdefault(identifier, {})
        # Playback UI text can be a short word label. Full source transcripts
        # and known word labels take precedence over these supplemental cues.
        if (
            not record.get("text")
            and transcript != record.get("label")
            and transcript.strip()
        ):
            record.update(text=transcript, text_source="duck-export/space.html")
    return metadata


def _probe(path: Path) -> dict:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name,sample_rate,channels:format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        data = json.loads(result.stdout)
        stream = data["streams"][0]
        duration = float(data["format"]["duration"])
        rate, channels = int(stream["sample_rate"]), int(stream["channels"])
        if (
            stream["codec_name"] != "mp3"
            or not math.isfinite(duration)
            or duration <= 0
            or rate <= 0
            or channels <= 0
        ):
            raise ValueError("Invalid MP3 stream metadata")
        return {"duration_seconds": duration, "sample_rate": rate, "channels": channels}
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
    ) as exc:
        raise ValueError(f"Cannot inspect audio with ffprobe: {path.name}") from exc


def _selected_audio(html: str, archive: zipfile.ZipFile, members: dict) -> dict:
    selected = {}
    seen_ids = set()
    for member in sorted(members):
        if member.startswith(ROOT + "assets/") and member.endswith(".mp3"):
            relative = member.removeprefix(ROOT + "assets/")
            if "/" in relative:
                raise ValueError(f"Nested audio asset path: {member}")
            identifier = _identifier(relative.removesuffix(".mp3"))
            if identifier.casefold() in seen_ids:
                raise ValueError(f"Duplicate audio identifier: {identifier}")
            seen_ids.add(identifier.casefold())
            selected[identifier] = (member, None)
    # These embedded bytes are the authoritative current page variants. Import
    # their matching archive member, never the older files with the same stem.
    for mapping in _literal(html, "AUDIO", required=False):
        if not isinstance(mapping, dict):
            raise ValueError("Malformed embedded AUDIO mapping")
        for identifier, uri in mapping.items():
            identifier = _identifier(identifier)
            if identifier.casefold() in seen_ids:
                raise ValueError(f"Duplicate audio identifier: {identifier}")
            prefix = "data:audio/mpeg;base64,"
            if not isinstance(uri, str) or not uri.startswith(prefix):
                raise ValueError("Malformed embedded MP3 data")
            try:
                data = base64.b64decode(uri[len(prefix) :], validate=True)
            except binascii.Error as exc:
                raise ValueError("Malformed embedded MP3 base64") from exc
            if not data or len(data) > MAX_MEMBER_BYTES:
                raise ValueError("Embedded audio exceeds size limit or is empty")
            group = (
                "tide-cbr-page" if identifier.startswith("tide_") else "why-cbr-page"
            )
            member = ROOT + f"audio/{group}/{identifier}.mp3"
            if _read(archive, members, member) != data:
                raise ValueError(
                    f"Current page audio does not match archive member: {identifier}"
                )
            seen_ids.add(identifier.casefold())
            selected[identifier] = (member, data)
    if not selected:
        raise ValueError("No current audio assets in source archive")
    return selected


def import_bundle(zip_path: Path, destination: Path) -> dict:
    """Create destination/manifest.json and audio/*.mp3, or leave no bundle.

    An existing destination is rejected. The ZIP is never extracted wholesale.
    The returned manifest equals the JSON written to disk; paths are relative
    to the bundle directory. Transcript status describes source availability,
    not independent verification of the spoken audio.
    """
    zip_path, destination = Path(zip_path).expanduser(), Path(destination).expanduser()
    if os.path.lexists(destination):
        raise FileExistsError(f"Bundle destination already exists: {destination}")
    if zip_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Archive exceeds size limit")
    staging = None
    try:
        with zipfile.ZipFile(zip_path) as archive:
            members = _archive_members(archive)
            html = _read(archive, members, ROOT + "space.html").decode("utf-8")
            metadata = _source_metadata(html, archive, members)
            selected = _selected_audio(html, archive, members)
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(
                tempfile.mkdtemp(prefix=".ducky-import-", dir=destination.parent)
            )
            (staging / "audio").mkdir()
            clips = []
            for identifier, (member, embedded) in sorted(selected.items()):
                data = (
                    embedded
                    if embedded is not None
                    else _read(archive, members, member)
                )
                relative = f"audio/{identifier}.mp3"
                path = staging / relative
                path.write_bytes(data)
                source = metadata.get(identifier, {})
                group = source.get(
                    "group",
                    "tide"
                    if identifier.startswith("tide_")
                    else "why"
                    if identifier.startswith(("sc_", "rb_"))
                    else "other",
                )
                text = source.get("text")
                clips.append(
                    {
                        "id": identifier,
                        "group": group,
                        "language": "zh"
                        if identifier.startswith(("tide_", "sc_", "rb_"))
                        else "en",
                        "label": source.get("label", text or identifier),
                        "text": text,
                        "text_status": "source_provided" if text else "unverified",
                        "text_source": source.get("text_source"),
                        "source_zip_member": member,
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "path": relative,
                        **_probe(path),
                    }
                )
            manifest = {
                "schema_version": 1,
                "voice_provenance": {
                    "basis": "user_report",
                    "provider": "Aria Muse",
                    "voice_id": "avocado_v2:MAI_01",
                    "english_speed": 92,
                    "chinese_speed": "default",
                    "redistribution_grant": None,
                },
                "clips": clips,
            }
            (staging / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            if os.path.lexists(destination):
                raise FileExistsError(
                    f"Bundle destination already exists: {destination}"
                )
            staging.rename(destination)
            staging = None
            return manifest
    except (zipfile.BadZipFile, UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid source archive or metadata") from exc
    finally:
        if staging is not None:
            shutil.rmtree(staging)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", type=Path)
    parser.add_argument(
        "--output", type=Path, required=True, help="New private bundle directory"
    )
    args = parser.parse_args(argv)
    try:
        manifest = import_bundle(args.zip_path, args.output)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Import failed: {exc}\n")
    print(f"Imported {len(manifest['clips'])} clips to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
