import base64
import hashlib
import json
import zipfile
from pathlib import Path

import pytest


def importer():
    try:
        from ducky_reachy_mini import import_assets
    except ImportError:
        pytest.fail("Asset importer is not implemented")
    return import_assets


def make_zip(tmp_path, extra=None, html=None):
    data = {
        "duck-export/space.html": html
        or """<script>
var SCENES={morning:{greeting:{id:'g01',text:'Hello!'},words:[['w01','sun','sun']],sentences:[]}};
var GOODBYES={morning:[['bye','Bye!']]};
var SCENE_ACTIONS={morning:{id:'play',text:'Play!',label:'开始'}};
var REVIEW_PACKS=[{id:'episode',intro:{id:'intro',text:'Welcome!'},scenes:[{words:[{word:'toy',audio:'toy'}]}],phrases:[{audio:'phrase',text:'Full phrase!',label:'Short'}]}];
</script>""",
        "duck-export/assets/w01.mp3": b"ID3-current-word",
        "duck-export/assets/toy.mp3": b"ID3-toy",
        "duck-export/assets/phrase.mp3": b"ID3-phrase",
        "duck-export/assets/unknown.mp3": b"ID3-unknown",
        "duck-export/audio/week0-words/w01.mp3": b"ID3-obsolete-word",
        "duck-export/lines/clips.tsv": "w01\tSun! Good morning, sun!\n",
    }
    data.update(extra or {})
    path = tmp_path / "source.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in data.items():
            archive.writestr(name, content)
    return path


@pytest.fixture
def probe(monkeypatch):
    module = importer()

    def run(argv, **kwargs):
        assert argv[0] == "ffprobe"
        assert Path(argv[-1]).read_bytes().startswith(b"ID3")
        from subprocess import CompletedProcess

        return CompletedProcess(
            argv,
            0,
            json.dumps(
                {
                    "streams": [
                        {"codec_name": "mp3", "sample_rate": "24000", "channels": 1}
                    ],
                    "format": {"duration": "1.25"},
                }
            ),
            "",
        )

    monkeypatch.setattr(module.subprocess, "run", run)
    return module


def test_preserves_current_bytes_and_full_source_transcript(tmp_path, probe):
    archive = make_zip(tmp_path)
    manifest = probe.import_bundle(archive, tmp_path / "bundle")
    clips = {clip["id"]: clip for clip in manifest["clips"]}
    assert len(clips) == 4
    word = clips["w01"]
    assert (tmp_path / "bundle" / word["path"]).read_bytes() == b"ID3-current-word"
    assert word["sha256"] == hashlib.sha256(b"ID3-current-word").hexdigest()
    assert word["text"] == "Sun! Good morning, sun!"
    assert word["label"] == "sun"
    assert word["text_status"] == "source_provided"
    assert word["source_zip_member"] == "duck-export/assets/w01.mp3"
    assert word["language"] == "en"
    assert (word["sample_rate"], word["channels"], word["duration_seconds"]) == (
        24000,
        1,
        1.25,
    )
    assert clips["phrase"]["text"] == "Full phrase!"
    assert clips["phrase"]["label"] == "Short"
    for identifier in ["toy", "unknown"]:
        assert clips[identifier]["text"] is None
        assert clips[identifier]["text_status"] == "unverified"
    assert manifest == json.loads((tmp_path / "bundle" / "manifest.json").read_text())
    assert manifest["voice_provenance"]["redistribution_grant"] is None


def test_imports_only_embedded_current_variant(tmp_path, probe):
    current = b"ID3-current-tide"
    default = make_zip(tmp_path)
    with zipfile.ZipFile(default) as z:
        html = z.read("duck-export/space.html").decode()
    html += (
        "<script>const AUDIO={tide_intro:'data:audio/mpeg;base64,"
        + base64.b64encode(current).decode()
        + "'};</script>"
    )
    archive = make_zip(
        tmp_path,
        {
            "duck-export/audio/tide-cbr-page/tide_intro.mp3": current,
            "duck-export/audio/tide/tide_intro.mp3": b"ID3-old",
            "duck-export/lines/tide-lines.tsv": "tide_intro.mp3\t你好！\n",
        },
        html,
    )
    clips = {
        c["id"]: c for c in probe.import_bundle(archive, tmp_path / "bundle")["clips"]
    }
    assert (
        clips["tide_intro"]["source_zip_member"]
        == "duck-export/audio/tide-cbr-page/tide_intro.mp3"
    )
    assert clips["tide_intro"]["text"] == "你好！"
    assert clips["tide_intro"]["language"] == "zh"
    assert (tmp_path / "bundle" / clips["tide_intro"]["path"]).read_bytes() == current


@pytest.mark.parametrize(
    "member",
    [
        "../escape.mp3",
        "/absolute.mp3",
        "duck-export/assets/../../escape.mp3",
        r"duck-export\assets\escape.mp3",
    ],
)
def test_rejects_unsafe_archive_members_without_writes(tmp_path, probe, member):
    archive = make_zip(tmp_path, {member: b"ID3"})
    with pytest.raises(ValueError, match="[Uu]nsafe"):
        probe.import_bundle(archive, tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()
    assert not (tmp_path / "escape.mp3").exists()


def test_rejects_duplicate_audio_ids(tmp_path, probe):
    archive = make_zip(tmp_path, {"duck-export/assets/sub/w01.mp3": b"ID3-duplicate"})
    with pytest.raises(ValueError, match="[Dd]uplicate|[Nn]ested"):
        probe.import_bundle(archive, tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()


def test_existing_bundle_is_unchanged(tmp_path, probe):
    destination = tmp_path / "bundle"
    destination.mkdir()
    (destination / "keep").write_text("unchanged")
    with pytest.raises(FileExistsError):
        probe.import_bundle(make_zip(tmp_path), destination)
    assert (destination / "keep").read_text() == "unchanged"
    assert list(destination.iterdir()) == [destination / "keep"]


def test_malformed_data_is_never_executed(tmp_path, probe):
    archive = make_zip(
        tmp_path, html="<script>var SCENES=(()=>{throw 'execute';})();</script>"
    )
    with pytest.raises(ValueError):
        probe.import_bundle(archive, tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()


def test_empty_archive_fails(tmp_path, probe):
    archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(archive, "w"):
        pass
    with pytest.raises(ValueError):
        probe.import_bundle(archive, tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()


def test_probe_failure_cleans_staging(tmp_path, probe, monkeypatch):
    def fail(*args, **kwargs):
        from subprocess import CalledProcessError

        raise CalledProcessError(1, args[0], stderr="invalid audio")

    monkeypatch.setattr(probe.subprocess, "run", fail)
    with pytest.raises(ValueError, match="audio|ffprobe"):
        probe.import_bundle(make_zip(tmp_path), tmp_path / "bundle")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["source.zip"]


def test_archive_size_cap(tmp_path, probe, monkeypatch):
    archive = make_zip(tmp_path)
    monkeypatch.setattr(probe, "MAX_ARCHIVE_BYTES", 10)
    with pytest.raises(ValueError, match="[Ll]imit|[Ll]arge"):
        probe.import_bundle(archive, tmp_path / "bundle")


def test_rejects_duplicate_id_between_assets_and_embedded(tmp_path, probe):
    archive = make_zip(tmp_path)
    with zipfile.ZipFile(archive) as z:
        html = z.read("duck-export/space.html").decode()
    html += "<script>var AUDIO={w01:'data:audio/mpeg;base64,SUQz'};</script>"
    archive = make_zip(tmp_path, html=html)
    with pytest.raises(ValueError, match="Duplicate audio identifier"):
        probe.import_bundle(archive, tmp_path / "bundle")


def test_rejects_mismatched_current_page_audio(tmp_path, probe):
    archive = make_zip(tmp_path)
    with zipfile.ZipFile(archive) as z:
        html = z.read("duck-export/space.html").decode()
    html += "<script>const AUDIO={tide_intro:'data:audio/mpeg;base64,SUQz'};</script>"
    archive = make_zip(
        tmp_path, {"duck-export/audio/tide-cbr-page/tide_intro.mp3": b"different"}, html
    )
    with pytest.raises(ValueError, match="does not match"):
        probe.import_bundle(archive, tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()


def test_rejects_duplicate_zip_member(tmp_path, probe):
    archive = make_zip(tmp_path)
    with zipfile.ZipFile(archive, "a") as z:
        with pytest.warns(UserWarning):
            z.writestr("duck-export/assets/w01.mp3", b"ID3-second")
    with pytest.raises(ValueError, match="Duplicate archive member"):
        probe.import_bundle(archive, tmp_path / "bundle")


def test_rejects_archive_symlink(tmp_path, probe):
    import stat

    archive = make_zip(tmp_path)
    info = zipfile.ZipInfo("duck-export/assets/link.mp3")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "a") as z:
        z.writestr(info, "/etc/passwd")
    with pytest.raises(ValueError, match="Unsafe"):
        probe.import_bundle(archive, tmp_path / "bundle")


def test_rejects_nonfinite_metadata(tmp_path, probe, monkeypatch):
    from subprocess import CompletedProcess

    monkeypatch.setattr(
        probe.subprocess,
        "run",
        lambda *a, **kw: CompletedProcess(
            a,
            0,
            '{"streams":[{"codec_name":"mp3","sample_rate":"24000","channels":1}],"format":{"duration":"NaN"}}',
            "",
        ),
    )
    with pytest.raises(ValueError, match="ffprobe"):
        probe.import_bundle(make_zip(tmp_path), tmp_path / "bundle")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["source.zip"]


def test_cli_import_reports_count(tmp_path, probe, capsys):
    assert (
        probe.main([str(make_zip(tmp_path)), "--output", str(tmp_path / "bundle")]) == 0
    )
    assert "Imported 4 clips" in capsys.readouterr().out


def test_rejects_case_colliding_ids_on_all_filesystems(tmp_path, probe):
    archive = make_zip(tmp_path, {"duck-export/assets/W01.mp3": b"ID3-collision"})
    with pytest.raises(ValueError, match="Duplicate audio identifier"):
        probe.import_bundle(archive, tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()


def test_static_speech_literals_supply_missing_transcripts_without_overwriting_tsv(
    tmp_path, probe
):
    archive = make_zip(tmp_path)
    with zipfile.ZipFile(archive) as z:
        html = z.read("duck-export/space.html").decode()
    html += """<script>
button.onclick=function(){sayPair('earth','Earth!','earth_sentence','We live on the Earth!')};
say('w01','sun');
say('unknown','A literal phrase!','wiggle');
</script>"""
    archive = make_zip(
        tmp_path,
        {
            "duck-export/assets/earth.mp3": b"ID3-earth",
            "duck-export/assets/earth_sentence.mp3": b"ID3-earth-sentence",
        },
        html,
    )
    clips = {
        c["id"]: c for c in probe.import_bundle(archive, tmp_path / "bundle")["clips"]
    }
    assert clips["earth"]["text"] == "Earth!"
    assert clips["earth_sentence"]["text"] == "We live on the Earth!"
    assert clips["earth"]["text_status"] == "source_provided"
    assert clips["unknown"]["text"] == "A literal phrase!"
    assert clips["w01"]["text"] == "Sun! Good morning, sun!"


def test_dynamic_speech_calls_are_not_treated_as_transcripts(tmp_path, probe):
    archive = make_zip(tmp_path)
    with zipfile.ZipFile(archive) as z:
        html = z.read("duck-export/space.html").decode()
    html += """<script>
sayPair('unknown', dynamicText, 'toy', 'Not a verified transcript');
say('toy', (()=>{throw 'must never execute'})());
say('unknown', 'literal prefix' + dynamicText);
</script>"""
    archive = make_zip(tmp_path, html=html)
    clips = {
        c["id"]: c for c in probe.import_bundle(archive, tmp_path / "bundle")["clips"]
    }
    assert clips["unknown"]["text"] is None
    assert clips["toy"]["text"] is None
