"""Independent local-format fixtures. No private data or vendor-generated expected arrays."""

from io import BytesIO
import stat
import struct
import zipfile
import pytest
from nmr_companion.errors import NmrError
from nmr_companion.formats import load_input

JCAMP = """##TITLE=Synthetic signed spectrum
##JCAMP-DX=5.00
##DATA TYPE=NMR SPECTRUM
##.OBSERVE NUCLEUS=13C
##XUNITS=PPM
##YUNITS=ARBITRARY UNITS
##FIRSTX=4
##LASTX=0
##NPOINTS=5
##XYDATA=(X++(Y..Y))
4 0 -3 0 5 0
##END=
"""


def test_jcamp_signed_descending_axis_and_original(tmp_path):
    path = tmp_path / "spectrum.dx"
    original = JCAMP.encode()
    path.write_bytes(original)
    result = load_input(path)
    s = result["spectra"][0]
    assert s["axis"] == [4, 3, 2, 1, 0]
    assert s["real"] == [0, -3, 0, 5, 0]
    assert s["imag"] is None and s["nucleus"] == "13C"
    assert s["domain"] == "frequency"
    assert s["metadata"]["fft_applied_on_import"] is False
    assert result["originals"] == [{"name": "spectrum.dx", "data": original}]


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.replace("##END=\n", ""),
        lambda s: s.replace("4 0 -3 0 5 0", "4 @A3B4"),
        lambda s: s.replace("##NPOINTS=5", "##NPOINTS=6"),
        lambda s: s.replace("##XUNITS=PPM", "##XUNITS=HZ"),
        lambda s: s.replace("##DATA TYPE=NMR SPECTRUM", "##DATA TYPE=LINK"),
        lambda s: s + JCAMP,
        lambda s: s.replace("##NPOINTS=5", "##NPOINTS=5\n##NPOINTS=5"),
        lambda s: s.replace("4 0 -3 0 5 0", "3 0 -3 0 5 0"),
    ],
)
def test_unsupported_or_inconsistent_jcamp_fails(tmp_path, change):
    path = tmp_path / "bad.dx"
    path.write_text(change(JCAMP), encoding="utf-8")
    with pytest.raises(NmrError):
        load_input(path)


def test_jcamp_scale_factors_and_xy_pairs(tmp_path):
    content = JCAMP.replace("##FIRSTX=4", "##XFACTOR=0.1\n##YFACTOR=2\n##FIRSTX=4")
    content = content.replace(
        "##XYDATA=(X++(Y..Y))\n4 0 -3 0 5 0", "##XYPOINTS=(XY..XY)\n40,0 30,-3 20,0 10,5 0,0"
    )
    path = tmp_path / "scaled.dx"
    path.write_text(content, encoding="utf-8")
    s = load_input(path)["spectra"][0]
    assert s["axis"] == [4, 3, 2, 1, 0] and s["real"] == [0, -6, 0, 10, 0]


def test_real_only_fid_keeps_stage_and_cannot_invent_quadrature(tmp_path):
    content = JCAMP.replace("NMR SPECTRUM", "NMR FID").replace("##XUNITS=PPM", "##XUNITS=MS")
    content = content.replace("##FIRSTX=4", "##FIRSTX=0").replace("##LASTX=0", "##LASTX=4")
    content = content.replace("4 0 -3 0 5 0", "0 0 -3 0 5 0")
    path = tmp_path / "time.dx"
    path.write_text(content, encoding="utf-8")
    result = load_input(path)
    s = result["spectra"][0]
    assert s["domain"] == "time" and s["axis"] == [0, 0.001, 0.002, 0.003, 0.004]
    assert s["imag"] is None and not s["metadata"]["complex_processing_ready"]
    assert result["warnings"]


def test_csv_rows_not_normalized_or_reordered(tmp_path):
    path = tmp_path / "delays.csv"
    original = b'time_ms,area,comment\r\n100,-2,"one,two"\r\n10,0,replicate\r\n10,3,replicate\r\n'
    path.write_bytes(original)
    result = load_input(path)
    table = result["tables"][0]
    assert table["columns"] == ["time_ms", "area", "comment"]
    assert [r["time_ms"] for r in table["rows"]] == ["100", "10", "10"]
    assert table["rows"][0]["area"] == "-2" and table["rows"][0]["comment"] == "one,two"
    assert result["originals"][0]["data"] == original
    assert result["warnings"]


@pytest.mark.parametrize("content", ["a,a\n1,2\n", "a,b\n1\n", "a,b\n", "a,b\n1,2,3\n"])
def test_csv_malformed_columns_rejected(tmp_path, content):
    path = tmp_path / "bad.csv"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(NmrError):
        load_input(path)


def write_raw(root, *, endian=0, dtype=0):
    root.mkdir(exist_ok=True)
    params = {
        "TD": 8,
        "AQ_mod": 3,
        "DTYPA": dtype,
        "BYTORDA": endian,
        "SW_h": 1000,
        "SFO1": 100,
        "O1": 400,
        "GRPDLY": 0,
        "NUC1": "<1H>",
    }
    (root / "acqus").write_text(
        "".join("##$" + k + "= " + str(v) + "\n" for k, v in params.items()), encoding="utf-8"
    )
    values = [1, -2, 3, -4, 5, -6, 7, -8]
    (root / "fid").write_bytes(
        struct.pack((">" if endian else "<") + ("8d" if dtype == 2 else "8i"), *values)
    )
    return params


@pytest.mark.parametrize("endian,dtype", [(0, 0), (1, 0), (0, 2), (1, 2)])
def test_bruker_raw_endianness_quadrature_dwell_and_zero_delay(tmp_path, endian, dtype):
    root = tmp_path / "raw"
    write_raw(root, endian=endian, dtype=dtype)
    s = load_input(root)["spectra"][0]
    assert s["real"] == [1, 3, 5, 7]
    assert s["imag"] == [-2, -4, -6, -8]
    assert s["axis"] == [0, 0.001, 0.002, 0.003]
    assert s["metadata"]["carrier_ppm"] == 4
    assert s["metadata"]["dwell_s"] == 0.001
    assert not s["metadata"]["digital_filter"]["applied"]
    assert not s["metadata"]["fft_applied_on_import"]


@pytest.mark.parametrize("endian,exponent", [(0, 3), (1, -2)])
def test_bruker_processed_scaling_axis_and_real_only_capability(tmp_path, endian, exponent):
    root = tmp_path / "processed"
    root.mkdir()
    params = {
        "SI": 4,
        "SF": 100,
        "SW_p": 400,
        "OFFSET": 6,
        "BYTORDP": endian,
        "DTYPP": 0,
        "NC_proc": exponent,
        "AXNUC": "<13C>",
    }
    (root / "procs").write_text(
        "".join("##$" + k + "= " + str(v) + "\n" for k, v in params.items()), encoding="utf-8"
    )
    (root / "1r").write_bytes(struct.pack((">" if endian else "<") + "4i", 1, -2, 0, 4))
    s = load_input(root)["spectra"][0]
    assert s["axis"] == [6, 5, 4, 3]
    assert s["real"] == [v * 2**exponent for v in [1, -2, 0, 4]]
    assert s["imag"] is None and s["nucleus"] == "13C"
    assert s["domain"] == "frequency" and not s["metadata"]["complex_processing_ready"]


def test_bruker_truncated_required_metadata_and_unknown_filter_fail(tmp_path):
    root = tmp_path / "raw"
    write_raw(root)
    path = root / "acqus"
    original = path.read_text()
    for text in [
        original.replace("##$NUC1= <1H>", "##$NUC1= <1H"),
        original.replace("##$TD= 8", "##$TD= (0..7)"),
        original.replace("##$GRPDLY= 0", "##$DSPFVS= 21\n##$DECIM= 2"),
        original.replace("##$TD= 8", "##$TD= 10"),
    ]:
        path.write_text(text, encoding="utf-8")
        with pytest.raises(NmrError):
            load_input(root)


@pytest.mark.parametrize(
    "name",
    [
        "../escape.csv",
        "/absolute.csv",
        "C:/drive.csv",
        "a\\windows.csv",
        "CON.csv",
        "trailing./x.csv",
    ],
)
def test_archive_traversal_and_aliases_rejected(tmp_path, name):
    path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, "delay\n1\n")
    # Windows ZipFile normalizes separators while writing; restore the raw header
    # spelling to exercise the same malformed bytes on Windows and Linux.
    if "\\" in name:
        path.write_bytes(path.read_bytes().replace(name.replace("\\", "/").encode(), name.encode()))
    with pytest.raises(NmrError):
        load_input(path)
    assert not (tmp_path.parent / "escape.csv").exists()


def test_archive_symlink_and_duplicate_case_rejected(tmp_path):
    for mode in ["symlink", "alias"]:
        path = tmp_path / (mode + ".zip")
        with zipfile.ZipFile(path, "w") as archive:
            if mode == "symlink":
                entry = zipfile.ZipInfo("link.csv")
                entry.create_system = 3
                entry.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(entry, "../../outside")
            else:
                archive.writestr("A.csv", "delay\n1\n")
                archive.writestr("a.csv", "delay\n2\n")
        with pytest.raises(NmrError):
            load_input(path)


def test_archive_preserves_container_and_members(tmp_path):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("run/spectrum.dx", JCAMP)
        archive.writestr("run/delays.csv", "delay_ms\n10\n")
    original = buffer.getvalue()
    path = tmp_path / "case.zip"
    path.write_bytes(original)
    result = load_input(path)
    assert len(result["spectra"]) == 1 and len(result["tables"]) == 1
    assert result["originals"][0] == {"name": "archive/case.zip", "data": original}
    assert {f["name"] for f in result["originals"][1:]} == {
        "members/run/spectrum.dx",
        "members/run/delays.csv",
    }


def test_multidimensional_inputs_fail_explicitly(tmp_path):
    root = tmp_path / "unsupported"
    root.mkdir()
    (root / "2rr").write_bytes(b"not a qualified matrix")
    with pytest.raises(NmrError) as failure:
        load_input(root)
    assert failure.value.code == "UNSUPPORTED_FORMAT"
