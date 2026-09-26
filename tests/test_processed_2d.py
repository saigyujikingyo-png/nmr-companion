"""Processed 2D reader fixtures with independently specified axes and block bytes."""

import json
import struct

import pytest

from nmr_companion.errors import NmrError
from nmr_companion.formats import load_input


def portable_grid(experiment="HSQC", nuclei=("1H", "13C")):
    return {
        "format": "nmr-companion-processed-2d",
        "schema_version": 1,
        "name": "Explicit processed correlation",
        "experiment": experiment,
        "x": {"unit": "ppm", "nucleus": nuclei[0], "values": [8, 6, 4, 2]},
        "y": {"unit": "ppm", "nucleus": nuclei[1], "values": [120, 100, 80]},
        "z": [[1, -2, 3, 4], [5, 6, -7, 8], [9, 10, 11, -12]],
    }


def write_portable(path, payload=None):
    original = json.dumps(portable_grid() if payload is None else payload).encode("utf-8")
    path.write_bytes(original)
    return original


def write_bruker(root, *, endian=0, dtype=0, exponent=2):
    root.mkdir(parents=True, exist_ok=True)
    parameters = {
        "procs": {
            "SI": 4,
            "XDIM": 2,
            "SF": 500,
            "SW_p": 4000,
            "OFFSET": 8,
            "BYTORDP": endian,
            "DTYPP": dtype,
            "NC_proc": exponent,
            "AXNUC": "<1H>",
        },
        "proc2s": {
            "SI": 4,
            "XDIM": 2,
            "SF": 125,
            "SW_p": 10000,
            "OFFSET": 160,
            "AXNUC": "<13C>",
            "NC_proc": 17,
        },
    }
    originals = {}
    for name, fields in parameters.items():
        original = "".join(f"##${key}= {value}\n" for key, value in fields.items()).encode()
        (root / name).write_bytes(original)
        originals[name] = original
    # Four 2x2 tiles, x varies fastest within each tile and between tiles.
    # Expected logical rows: [1,-2,3,4], [5,6,-7,8], [9,10,11,-12], [13,14,15,16].
    stored = [1, -2, 5, 6, 3, 4, -7, 8, 9, 10, 13, 14, 11, -12, 15, 16]
    original = struct.pack((">" if endian else "<") + ("16d" if dtype == 2 else "16i"), *stored)
    (root / "2rr").write_bytes(original)
    originals["2rr"] = original
    return originals


def test_portable_hsqc_explicit_axes_signed_grid_and_original(tmp_path):
    path = tmp_path / "correlation.json"
    original = write_portable(path)
    result = load_input(path)
    assert not result["spectra"] and len(result["grids"]) == 1
    grid = result["grids"][0]
    assert grid["x"] == [8, 6, 4, 2]
    assert grid["y"] == [120, 100, 80]
    assert grid["z"] == [[1, -2, 3, 4], [5, 6, -7, 8], [9, 10, 11, -12]]
    assert grid["nuclei"] == ["1H", "13C"]
    assert grid["metadata"]["experiment"] == "HSQC"
    assert grid["source_names"] == [path.name]
    assert result["originals"] == [{"name": path.name, "data": original}]


@pytest.mark.parametrize("endian,dtype,exponent", [(0, 0, 2), (1, 0, -2), (0, 2, 0), (1, 2, 1)])
def test_bruker_2rr_submatrices_scaling_axes_and_originals(tmp_path, endian, dtype, exponent):
    root = tmp_path / "processed"
    originals = write_bruker(root, endian=endian, dtype=dtype, exponent=exponent)
    result = load_input(root)
    grid = result["grids"][0]
    assert grid["x"] == [8, 6, 4, 2]
    assert grid["y"] == [160, 140, 120, 100]
    expected = [[1, -2, 3, 4], [5, 6, -7, 8], [9, 10, 11, -12], [13, 14, 15, 16]]
    assert grid["z"] == [[value * 2**exponent for value in row] for row in expected]
    assert grid["nuclei"] == ["1H", "13C"]
    assert grid["metadata"]["experiment"] is None
    assert grid["metadata"]["axis_order"] == {"x": "F2", "y": "F1", "z": "rows_y_columns_x"}
    assert not grid["metadata"]["fft_applied_on_import"]
    assert set(grid["source_names"]) == set(originals)
    assert {item["name"]: item["data"] for item in result["originals"]} == originals


@pytest.mark.parametrize(
    "experiment,nuclei",
    [("COSY", ("1H", "1H")), ("HSQC", ("1H", "15N")), ("HSQC", ("15N", "1H"))],
)
def test_portable_experiment_and_both_hsqc_nucleus_orientations(tmp_path, experiment, nuclei):
    payload = portable_grid(experiment, nuclei)
    path = tmp_path / "axes.json"
    write_portable(path, payload)
    grid = load_input(path)["grids"][0]
    assert grid["nuclei"] == list(nuclei)
    assert grid["metadata"]["experiment"] == experiment
    assert grid["z"] == payload["z"]


def test_portable_reversed_hsqc_axis_orientation_is_not_transposed_on_import(tmp_path):
    payload = portable_grid()
    payload["x"], payload["y"] = payload["y"], payload["x"]
    payload["z"] = [[1, 5, 9], [-2, 6, 10], [3, -7, 11], [4, 8, -12]]
    path = tmp_path / "carbon-x.json"
    write_portable(path, payload)
    grid = load_input(path)["grids"][0]
    assert grid["nuclei"] == ["13C", "1H"]
    assert grid["x"] == [120, 100, 80] and grid["y"] == [8, 6, 4, 2]
    assert grid["z"] == payload["z"]


@pytest.mark.parametrize("experiment", [None, "HSQC/COSY", "HMQC", "hsqc", ["HSQC"]])
def test_portable_ambiguous_or_unsupported_experiments_fail(tmp_path, experiment):
    payload = portable_grid()
    payload["experiment"] = experiment
    path = tmp_path / "invalid.json"
    write_portable(path, payload)
    with pytest.raises(NmrError) as failure:
        load_input(path)
    assert failure.value.code == "INVALID_METADATA"


@pytest.mark.parametrize(
    "key_path,value,code",
    [
        (("x", "nucleus"), None, "INVALID_METADATA"),
        (("x", "nucleus"), "1H/13C", "INVALID_METADATA"),
        (("x", "nucleus"), "13C", "INVALID_METADATA"),
        (("y", "nucleus"), "1H", "INVALID_METADATA"),
        (("x", "unit"), "Hz", "INVALID_METADATA"),
        (("x", "values"), [8, 6, 6, 2], "INVALID_DATA"),
        (("y", "values"), [80, 120, 100], "INVALID_DATA"),
        (("x", "values"), [True, 6, 4, 2], "INVALID_DATA"),
        (("x", "values"), ["8", 6, 4, 2], "INVALID_DATA"),
        (("x", "values"), [8, float("inf"), 4, 2], "INVALID_DATA"),
        (("z",), [[1, 2], [3, 4], [5, 6]], "INVALID_DATA"),
        (("z",), [[1, 2, 3, 4]], "INVALID_DATA"),
        (("z",), [1, 2, 3], "INVALID_DATA"),
        (("z",), [[1, 2, 3, 4], [5, 6, 7, 8], [9, "10", 11, 12]], "INVALID_DATA"),
        (("z",), [[1, 2, 3, 4], [5, 6, 7, 8], [9, False, 11, 12]], "INVALID_DATA"),
        (("z",), [[1, 2, 3, 4], [5, 6, 7, 8], [9, float("nan"), 11, 12]], "INVALID_DATA"),
        (("schema_version",), True, "UNSUPPORTED_FORMAT"),
        (("schema_version",), 2, "UNSUPPORTED_FORMAT"),
        (("format",), "other", "UNSUPPORTED_FORMAT"),
        (("name",), "", "INVALID_METADATA"),
    ],
)
def test_portable_invalid_axes_values_and_contract_fail(tmp_path, key_path, value, code):
    payload = portable_grid()
    target = payload
    for key in key_path[:-1]:
        target = target[key]
    target[key_path[-1]] = value
    path = tmp_path / "invalid.json"
    write_portable(path, payload)
    with pytest.raises(NmrError) as failure:
        load_input(path)
    assert failure.value.code == code


def test_portable_missing_ambiguous_or_conflicting_labels_fail(tmp_path):
    path = tmp_path / "invalid.json"
    missing = portable_grid()
    del missing["experiment"]
    ambiguous = portable_grid()
    ambiguous["nuclei"] = ["13C", "1H"]
    conflict = portable_grid("COSY")
    axis_missing = portable_grid()
    del axis_missing["y"]["nucleus"]
    for payload in (missing, ambiguous, conflict, axis_missing):
        write_portable(path, payload)
        with pytest.raises(NmrError):
            load_input(path)
    original = json.dumps(portable_grid())
    for raw in (
        original.replace('"experiment": "HSQC"', '"experiment": "COSY", "experiment": "HSQC"'),
        original.replace('"nucleus": "13C"', '"nucleus": "1H", "nucleus": "13C"'),
        original.replace('"values": [8, 6, 4, 2]', '"values": [8, 1e999, 4, 2]'),
        "[" * 1100 + "0" + "]" * 1100,
    ):
        path.write_text(raw, encoding="utf-8")
        with pytest.raises(NmrError):
            load_input(path)


def test_portable_cell_limit_precedes_allocation_and_accepts_one_million(tmp_path):
    path = tmp_path / "limit.json"
    payload = portable_grid("COSY", ("1H", "1H"))
    payload["x"]["values"] = list(range(1001))
    payload["y"]["values"] = list(range(1000))
    payload["z"] = []
    write_portable(path, payload)
    with pytest.raises(NmrError) as failure:
        load_input(path)
    assert failure.value.code == "INPUT_LIMIT"
    payload["x"]["values"] = list(range(1000))
    payload["z"] = [[0] * 1000 for _ in range(1000)]
    payload["z"][42][73] = -7
    write_portable(path, payload)
    grid = load_input(path)["grids"][0]
    assert len(grid["z"]) == 1000 and len(grid["z"][0]) == 1000
    assert grid["z"][42][73] == -7


def change_parameter(root, filename, key, value):
    path = root / filename
    lines = [line for line in path.read_text().splitlines() if not line.startswith(f"##${key}=")]
    if value is not None:
        lines.append(f"##${key}= {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_bruker_rectangular_tiles_distinguish_x_and_y(tmp_path):
    root = tmp_path / "rectangular"
    write_bruker(root, exponent=0)
    change_parameter(root, "procs", "SI", 6)
    change_parameter(root, "procs", "XDIM", 3)
    change_parameter(root, "procs", "SW_p", 6000)
    # 2x3 tiles in a 4x6 matrix, written independently of nmrglue's writer.
    stored = [1, 2, 3, 7, 8, 9, 4, 5, 6, 10, 11, 12, 13, 14, 15, 19, 20, 21, 16, 17, 18, 22, 23, 24]
    (root / "2rr").write_bytes(struct.pack("<24i", *stored))
    grid = load_input(root)["grids"][0]
    assert grid["x"] == [8, 6, 4, 2, 0, -2]
    assert grid["y"] == [160, 140, 120, 100]
    assert grid["z"] == [
        list(range(1, 7)),
        list(range(7, 13)),
        list(range(13, 19)),
        list(range(19, 25)),
    ]
    assert grid["metadata"]["submatrix_shape"] == [2, 3]


@pytest.mark.parametrize("filename", ["procs", "proc2s"])
@pytest.mark.parametrize("key", ["SI", "XDIM", "SF", "SW_p", "OFFSET", "AXNUC"])
def test_bruker_missing_axis_metadata_fails_without_guessing(tmp_path, filename, key):
    root = tmp_path / "missing"
    write_bruker(root)
    change_parameter(root, filename, key, None)
    with pytest.raises(NmrError) as failure:
        load_input(root)
    assert failure.value.code == "INVALID_METADATA"


@pytest.mark.parametrize(
    "filename,key,value,code",
    [
        ("proc2s", "XDIM", 3, "UNSUPPORTED_FORMAT"),
        ("procs", "XDIM", 0, "INVALID_METADATA"),
        ("proc2s", "SF", 0, "INVALID_METADATA"),
        ("procs", "SW_p", -1, "INVALID_METADATA"),
        ("proc2s", "OFFSET", "NaN", "INVALID_METADATA"),
        ("procs", "OFFSET", "1e308", "INVALID_DATA"),
        ("proc2s", "AXNUC", "<H>", "INVALID_METADATA"),
        ("procs", "AXNUC", "<1H", "INVALID_METADATA"),
        ("proc2s", "STSI", 2, "UNSUPPORTED_FORMAT"),
        ("procs", "STSR", 1, "UNSUPPORTED_FORMAT"),
        ("procs", "DTYPP", 1, "UNSUPPORTED_FORMAT"),
        ("procs", "BYTORDP", 2, "INVALID_METADATA"),
        ("procs", "NC_proc", None, "INVALID_METADATA"),
    ],
)
def test_bruker_invalid_axis_storage_or_crop_fails(tmp_path, filename, key, value, code):
    root = tmp_path / "invalid"
    write_bruker(root)
    change_parameter(root, filename, key, value)
    with pytest.raises(NmrError) as failure:
        load_input(root)
    assert failure.value.code == code


@pytest.mark.parametrize("first_value,exponent", [(float("nan"), 0), (float("inf"), 0), (1e308, 2)])
def test_bruker_nonfinite_or_scaled_overflow_fails(tmp_path, first_value, exponent):
    root = tmp_path / "invalid-float"
    write_bruker(root, dtype=2, exponent=exponent)
    (root / "2rr").write_bytes(struct.pack("<16d", first_value, *range(1, 16)))
    with pytest.raises(NmrError) as failure:
        load_input(root)
    assert failure.value.code == "INVALID_DATA"


@pytest.mark.parametrize("length_delta", [-4, 4])
def test_bruker_incorrect_binary_length_fails(tmp_path, length_delta):
    root = tmp_path / "length"
    write_bruker(root)
    path = root / "2rr"
    original = path.read_bytes()
    path.write_bytes(
        original[:length_delta] if length_delta < 0 else original + b"\0" * length_delta
    )
    with pytest.raises(NmrError) as failure:
        load_input(root)
    assert failure.value.code == "INVALID_DATA"


def test_bruker_cell_limit_is_checked_before_binary_reader(tmp_path):
    root = tmp_path / "limit"
    write_bruker(root)
    change_parameter(root, "procs", "SI", 1002)
    change_parameter(root, "proc2s", "SI", 1000)
    with pytest.raises(NmrError) as failure:
        load_input(root)
    assert failure.value.code == "INPUT_LIMIT"


@pytest.mark.parametrize("forbidden", ["ser", "proc3s", "3rrr", "4rrrr"])
def test_processed_reader_does_not_enable_raw_or_higher_dimensions(tmp_path, forbidden):
    root = tmp_path / "unsupported"
    write_bruker(root)
    (root / forbidden).write_bytes(b"unsupported")
    with pytest.raises(NmrError) as failure:
        load_input(root)
    assert failure.value.code == "UNSUPPORTED_FORMAT"


def test_bruker_evidenced_acquisition_nuclei_and_experiment_bind_to_originals(tmp_path):
    root = tmp_path / "bundle"
    pdata = root / "run" / "pdata" / "7"
    write_bruker(pdata)
    change_parameter(pdata, "procs", "AXNUC", None)
    change_parameter(pdata, "proc2s", "AXNUC", None)
    (root / "run" / "acqus").write_bytes(b"##$NUC1= <1H>\n##$EXP= <HSQC>\n")
    (root / "run" / "acqu2s").write_bytes(b"##$NUC1= <13C>\n")
    result = load_input(root)
    grid = result["grids"][0]
    assert grid["nuclei"] == ["1H", "13C"]
    assert grid["metadata"]["experiment"] == "HSQC"
    assert grid["metadata"]["experiment_source"] == "acqus.EXP"
    assert set(grid["source_names"]) == {
        "run/pdata/7/2rr",
        "run/pdata/7/procs",
        "run/pdata/7/proc2s",
        "run/acqus",
        "run/acqu2s",
    }
    assert set(grid["source_names"]) == {item["name"] for item in result["originals"]}
    (root / "run" / "acqus").write_bytes(b"##$NUC1= <1H>\n##$EXP= <hsqcedetgpsisp2.3>\n")
    result = load_input(root)
    assert result["grids"][0]["metadata"]["experiment"] is None
    assert any("unknown" in warning for warning in result["warnings"])


def test_bruker_conflicting_nucleus_and_experiment_evidence_fails(tmp_path):
    root = tmp_path / "conflict"
    write_bruker(root)
    for declared in (b"##$NUC1= <13C>\n", b"##$NUC1= <1H>\n##$EXP= <COSY>\n"):
        (root / "acqus").write_bytes(declared)
        with pytest.raises(NmrError) as failure:
            load_input(root)
        assert failure.value.code == "INVALID_METADATA"


def test_unrelated_json_sidecars_keep_existing_import_behavior(tmp_path):
    root = tmp_path / "sidecars"
    root.mkdir()
    (root / "delays.csv").write_bytes(b"delay_ms\n1\n2\n")
    (root / "settings.json").write_bytes(b'{"format":"unrelated","unit":"Hz"}')
    (root / "partial.json").write_bytes(b'{"interrupted":')
    result = load_input(root)
    assert len(result["tables"]) == 1 and result["grids"] == []
    assert len(result["originals"]) == 3
    (root / "strict.nmr2d.json").write_bytes(b'{"interrupted":')
    with pytest.raises(NmrError) as failure:
        load_input(root)
    assert failure.value.code == "INVALID_FORMAT"


def test_zip_binds_each_grid_to_exact_members_and_preserves_archive(tmp_path):
    import zipfile

    root = tmp_path / "source"
    originals = write_bruker(root)
    portable = json.dumps(portable_grid()).encode()
    path = tmp_path / "processed.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in originals.items():
            archive.writestr("bruker/" + name, data)
        archive.writestr("portable/correlation.json", portable)
    archive_bytes = path.read_bytes()
    result = load_input(path)
    original_map = {item["name"]: item["data"] for item in result["originals"]}
    assert original_map["archive/processed.zip"] == archive_bytes
    bruker, portable_grid_result = result["grids"]
    assert set(bruker["source_names"]) == {"members/bruker/" + name for name in originals}
    for name, data in originals.items():
        assert original_map["members/bruker/" + name] == data
    assert portable_grid_result["source_names"] == ["members/portable/correlation.json"]
    assert original_map[portable_grid_result["metadata"]["source_name"]] == portable
    assert set(bruker["source_names"]).isdisjoint(portable_grid_result["source_names"])


def test_bruker_homonuclear_axes_do_not_imply_cosy_without_explicit_label(tmp_path):
    root = tmp_path / "cosy"
    write_bruker(root, exponent=0)
    for key, value in (("AXNUC", "<1H>"), ("SF", 500), ("SW_p", 4000), ("OFFSET", 8)):
        change_parameter(root, "proc2s", key, value)
    grid = load_input(root)["grids"][0]
    assert grid["nuclei"] == ["1H", "1H"]
    assert grid["x"] == grid["y"] == [8, 6, 4, 2]
    assert grid["metadata"]["experiment"] is None
    (root / "acqus").write_bytes(b"##$NUC1= <1H>\n##$EXP= <COSY>\n")
    grid = load_input(root)["grids"][0]
    assert grid["metadata"]["experiment"] == "COSY"
    assert grid["z"][0][1] == -2


def test_duplicate_format_marker_in_mixed_bundle_cannot_hide_invalid_grid(tmp_path):
    root = tmp_path / "mixed"
    root.mkdir()
    (root / "delays.csv").write_bytes(b"delay_ms\n1\n2\n")
    raw = json.dumps(portable_grid()).replace(
        '"format": "nmr-companion-processed-2d"',
        '"format": "nmr-companion-processed-2d", "format": "unrelated"',
    )
    (root / "ambiguous.json").write_text(raw, encoding="utf-8")
    with pytest.raises(NmrError) as failure:
        load_input(root)
    assert failure.value.code == "INVALID_FORMAT"


def test_project_import_retains_grid_source_dependencies_and_reopens(tmp_path):
    import hashlib
    import zipfile

    from nmr_companion.service import Service

    root = tmp_path / "processed"
    source_bytes = write_bruker(root)
    portable = json.dumps(portable_grid()).encode()
    path = tmp_path / "inputs.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in source_bytes.items():
            archive.writestr("bruker/" + name, data)
        archive.writestr("portable/reference.nmr2d.json", portable)
    source_bytes = {"members/bruker/" + name: data for name, data in source_bytes.items()}
    source_bytes["members/portable/reference.nmr2d.json"] = portable
    source_bytes["archive/inputs.zip"] = path.read_bytes()
    service = Service(tmp_path / "source-binding.nmrproj")
    service.create("Processed grid source binding")
    service.apply(0, "import-grids", {"op": "import", "path": str(path)})
    project = service.read()
    assert len(project.grids) == 2
    by_source = {grid.metadata["source_name"]: grid for grid in project.grids.values()}
    bruker = by_source["members/bruker/2rr"]
    reference = by_source["members/portable/reference.nmr2d.json"]
    assert set(bruker.source_ids) == {
        hashlib.sha256(data).hexdigest()
        for name, data in source_bytes.items()
        if name.startswith("members/bruker/")
    }
    assert reference.source_ids == [hashlib.sha256(portable).hexdigest()]
    with service.store.connection() as db:
        for name, data in source_bytes.items():
            digest = hashlib.sha256(data).hexdigest()
            assert name in project.sources[digest].names
            assert (
                db.execute("SELECT data FROM originals WHERE sha256=?", (digest,)).fetchone()[0]
                == data
            )
    assert Service(service.store.path).read().model_dump() == project.model_dump()


def write_processing_profile(root, *, width=400):
    root.mkdir(parents=True, exist_ok=True)
    fields = {
        "SI": 4,
        "SF": 100,
        "SW_p": width,
        "OFFSET": 6,
        "BYTORDP": 0,
        "DTYPP": 0,
        "NC_proc": 0,
        "AXNUC": "<1H>",
    }
    (root / "procs").write_bytes(
        "".join(f"##${key}= {value}\n" for key, value in fields.items()).encode()
    )
    (root / "1r").write_bytes(struct.pack("<4i", 1, -2, 0, 4))


def write_processing_selection_bundle(root):
    write_processing_profile(root / "run" / "pdata" / "1")
    write_processing_profile(root / "run" / "pdata" / "700", width=-10000000)
    (root / "run" / "acqus").write_bytes(
        b"##$TD= 8\n##$AQ_mod= 3\n##$DTYPA= 0\n##$BYTORDA= 0\n"
        b"##$SW_h= 1000\n##$SFO1= 100\n##$O1= 400\n##$GRPDLY= 0\n##$NUC1= <1H>\n"
    )
    (root / "run" / "fid").write_bytes(struct.pack("<8i", 1, -2, 3, -4, 5, -6, 7, -8))
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_explicit_processing_selection_preserves_raw_and_undecoded_originals(tmp_path):
    root = tmp_path / "selection"
    originals = write_processing_selection_bundle(root)
    with pytest.raises(NmrError) as default_failure:
        load_input(root)
    assert default_failure.value.code == "INVALID_METADATA"
    result = load_input(root, bruker_processing_numbers=[1])
    assert {s["name"] for s in result["spectra"]} == {"run/fid", "run/pdata/1/1r"}
    raw, processed = result["spectra"]
    assert raw["real"] == [1, 3, 5, 7] and raw["imag"] == [-2, -4, -6, -8]
    assert processed["real"] == [1, -2, 0, 4]
    assert {item["name"]: item["data"] for item in result["originals"]} == originals
    selection = processed["metadata"]["bruker_processing_selection"]
    assert selection["requested"] == [1] and selection["discovered"] == [1, 700]
    assert selection["decoded_profiles"] == ["run/pdata/1"]
    assert selection["skipped_profiles"] == ["run/pdata/700"]
    assert selection["skipped_status"] == "preserved_not_decoded_or_qualified"
    assert raw["metadata"]["bruker_processing_selection"] == selection
    assert any(
        "700" in warning and "not decoded or qualified" in warning for warning in result["warnings"]
    )


@pytest.mark.parametrize(
    "selection", [[], [1, 1], [0], [-1], [True], [1.0], ["1"], [[1]], "1", 1, (1,), [1] * 1025]
)
def test_processing_selection_requires_explicit_unique_positive_integers(tmp_path, selection):
    root = tmp_path / "selection"
    write_processing_selection_bundle(root)
    with pytest.raises(NmrError) as failure:
        load_input(root, bruker_processing_numbers=selection)
    assert failure.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("selection", [[2], [1, 2]])
def test_processing_selection_missing_number_fails_with_discovery(tmp_path, selection):
    root = tmp_path / "selection"
    write_processing_selection_bundle(root)
    with pytest.raises(NmrError) as failure:
        load_input(root, bruker_processing_numbers=selection)
    assert failure.value.code == "NOT_FOUND"
    assert "Discovered Bruker processing numbers: 1, 700" in failure.value.message


def test_processing_selection_does_not_accept_invalid_selected_profile(tmp_path):
    root = tmp_path / "selection"
    write_processing_selection_bundle(root)
    for selection in (None, [700], [1, 700]):
        with pytest.raises(NmrError) as failure:
            load_input(root, bruker_processing_numbers=selection)
        assert failure.value.code == "INVALID_METADATA"
        assert "run/pdata/700/1r" in failure.value.message
        assert "Discovered Bruker processing numbers: 1, 700" in failure.value.message


def test_processing_selection_applies_to_every_experiment_and_processed_dimension(tmp_path):
    root = tmp_path / "selection"
    write_processing_selection_bundle(root)
    write_bruker(root / "other" / "pdata" / "1", exponent=0)
    write_processing_profile(root / "third" / "pdata" / "1")
    result = load_input(root, bruker_processing_numbers=[1])
    assert {s["name"] for s in result["spectra"]} == {
        "run/fid",
        "run/pdata/1/1r",
        "third/pdata/1/1r",
    }
    grid = result["grids"][0]
    assert grid["name"] == "other/pdata/1/2rr"
    assert grid["nuclei"] == ["1H", "13C"] and grid["z"][0][1] == -2
    assert grid["metadata"]["bruker_processing_selection"]["decoded_profiles"] == [
        "other/pdata/1",
        "run/pdata/1",
        "third/pdata/1",
    ]


def test_processing_selection_zip_keeps_all_member_bytes_and_archive_identity(tmp_path):
    import zipfile

    root = tmp_path / "source"
    originals = write_processing_selection_bundle(root)
    archive_path = tmp_path / "selected.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, data in originals.items():
            archive.writestr(name, data)
    archive_bytes = archive_path.read_bytes()
    result = load_input(archive_path, bruker_processing_numbers=[1])
    expected = {"members/" + name: data for name, data in originals.items()}
    expected["archive/selected.zip"] = archive_bytes
    assert {item["name"]: item["data"] for item in result["originals"]} == expected
    for spectrum in result["spectra"]:
        selection = spectrum["metadata"]["bruker_processing_selection"]
        assert selection["decoded_profiles"] == ["members/run/pdata/1"]
        assert selection["skipped_profiles"] == ["members/run/pdata/700"]
        assert spectrum["metadata"]["source_name"] in expected


@pytest.mark.parametrize("target", ["pdata", "profile"])
def test_processing_selection_recognizes_explicit_input_directory_context(tmp_path, target):
    root = tmp_path / "run" / "pdata"
    write_processing_profile(root / "1")
    selected = root if target == "pdata" else root / "1"
    result = load_input(selected, bruker_processing_numbers=[1])
    spectrum = result["spectra"][0]
    selection = spectrum["metadata"]["bruker_processing_selection"]
    assert selection["discovered"] == [1]
    assert selection["decoded_profiles"] == (["1"] if target == "pdata" else ["."])
    assert selection["input_directory_context"] == ("pdata" if target == "pdata" else "pdata/1")
    assert set(item["name"] for item in result["originals"]) == (
        {"1/procs", "1/1r"} if target == "pdata" else {"procs", "1r"}
    )


def test_processing_selection_never_guesses_a_flattened_profile_number(tmp_path):
    root = tmp_path / "flat"
    write_processing_profile(root)
    with pytest.raises(NmrError) as failure:
        load_input(root, bruker_processing_numbers=[1])
    assert failure.value.code == "NOT_FOUND"
    assert "Discovered Bruker processing numbers: none" in failure.value.message
    assert len(load_input(root)["spectra"]) == 1
    write_processing_profile(root / "run" / "pdata" / "1")
    with pytest.raises(NmrError) as mixed:
        load_input(root, bruker_processing_numbers=[1])
    assert mixed.value.code == "INVALID_ARGUMENT"


def test_processing_selection_does_not_succeed_from_a_parameter_only_directory(tmp_path):
    root = tmp_path / "selection"
    (root / "run" / "pdata" / "1").mkdir(parents=True)
    (root / "run" / "pdata" / "1" / "procs").write_bytes(b"##$SI= 4\n")
    (root / "delays.csv").write_bytes(b"delay_ms\n10\n20\n")
    with pytest.raises(NmrError) as failure:
        load_input(root, bruker_processing_numbers=[1])
    assert failure.value.code == "NOT_FOUND" and "numbers: 1" in failure.value.message


def test_processing_selection_keeps_raw_validation_and_multidimensional_rejection(tmp_path):
    root = tmp_path / "selection"
    write_processing_selection_bundle(root)
    raw = root / "run" / "fid"
    original = raw.read_bytes()
    raw.write_bytes(original[:-4])
    with pytest.raises(NmrError) as invalid_raw:
        load_input(root, bruker_processing_numbers=[1])
    assert invalid_raw.value.code == "INVALID_DATA"
    raw.write_bytes(original)
    (root / "run" / "pdata" / "700" / "ser").write_bytes(b"unqualified raw multidimensional")
    with pytest.raises(NmrError) as multidimensional:
        load_input(root, bruker_processing_numbers=[1])
    assert multidimensional.value.code == "UNSUPPORTED_FORMAT"


def test_processing_selection_preserves_but_does_not_qualify_unselected_higher_dimension(tmp_path):
    root = tmp_path / "selection"
    write_processing_profile(root / "run" / "pdata" / "1")
    unsupported = root / "run" / "pdata" / "700" / "3rrr"
    unsupported.parent.mkdir(parents=True)
    unsupported.write_bytes(b"unqualified processed volume")
    result = load_input(root, bruker_processing_numbers=[1])
    assert len(result["spectra"]) == 1
    assert result["spectra"][0]["metadata"]["bruker_processing_selection"]["skipped_profiles"] == [
        "run/pdata/700"
    ]
    for selection in (None, [700]):
        with pytest.raises(NmrError) as failure:
            load_input(root, bruker_processing_numbers=selection)
        assert failure.value.code == "UNSUPPORTED_FORMAT"


def test_processing_selection_cannot_hide_unsafe_zip_members_or_capture_limits(
    tmp_path, monkeypatch
):
    import zipfile

    from nmr_companion import formats

    root = tmp_path / "source"
    originals = write_processing_selection_bundle(root)
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, data in originals.items():
            archive.writestr(name, data)
        archive.writestr("run/pdata/700/../escape.csv", b"x\n1\n")
    with pytest.raises(NmrError) as unsafe:
        load_input(archive_path, bruker_processing_numbers=[1])
    assert unsafe.value.code == "UNSAFE_INPUT"
    monkeypatch.setattr(formats, "MAX_ORIGINAL_BYTES", 1024)
    (root / "run" / "pdata" / "700" / "large.bin").write_bytes(b"x" * 1025)
    with pytest.raises(NmrError) as oversized:
        load_input(root, bruker_processing_numbers=[1])
    assert oversized.value.code == "INPUT_LIMIT"


def test_processing_selection_leaves_csv_outside_profiles_available(tmp_path):
    root = tmp_path / "selection"
    write_processing_selection_bundle(root)
    (root / "delays.csv").write_bytes(b"delay_ms\n10\n20\n")
    (root / "run" / "pdata" / "700" / "invalid.csv").write_bytes(b"a,b\n1\n")
    result = load_input(root, bruker_processing_numbers=[1])
    assert [table["name"] for table in result["tables"]] == ["delays.csv"]
    assert "run/pdata/700/invalid.csv" in {item["name"] for item in result["originals"]}


@pytest.mark.parametrize("selection", [[1000000], list(range(1, 66))])
def test_processing_selection_matches_command_bounds(tmp_path, selection):
    root = tmp_path / "selection"
    write_processing_selection_bundle(root)
    with pytest.raises(NmrError) as failure:
        load_input(root, bruker_processing_numbers=selection)
    assert failure.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("directory,number", [("0001", 1), ("999999", 999999)])
def test_processing_selection_decimal_identity_and_upper_boundary(tmp_path, directory, number):
    root = tmp_path / "selection"
    write_processing_profile(root / "run" / "pdata" / directory)
    result = load_input(root, bruker_processing_numbers=[number])
    assert result["spectra"][0]["name"] == f"run/pdata/{directory}/1r"
    assert result["spectra"][0]["metadata"]["bruker_processing_selection"]["discovered"] == [number]


def test_processing_selection_uses_nearest_numbered_directory(tmp_path):
    root = tmp_path / "selection"
    write_processing_profile(root / "run" / "pdata" / "1")
    nested = root / "run" / "pdata" / "1" / "nested" / "pdata" / "700"
    write_processing_profile(nested, width=-1)
    result = load_input(root, bruker_processing_numbers=[1])
    assert [s["name"] for s in result["spectra"]] == ["run/pdata/1/1r"]
    selection = result["spectra"][0]["metadata"]["bruker_processing_selection"]
    assert selection["skipped_profiles"] == ["run/pdata/1/nested/pdata/700"]
    assert selection["discovered"] == [1, 700]


def test_processing_selection_accepts_relative_input_directory_context(tmp_path, monkeypatch):
    selected = tmp_path / "run" / "pdata" / "1"
    write_processing_profile(selected)
    monkeypatch.chdir(selected)
    result = load_input(".", bruker_processing_numbers=[1])
    assert result["spectra"][0]["metadata"]["bruker_processing_selection"]["decoded_profiles"] == [
        "."
    ]


def test_processing_selection_applies_object_limit_after_scope_selection(tmp_path):
    root = tmp_path / "selection"
    for number in range(1, 66):
        write_processing_profile(root / "run" / "pdata" / str(number))
    with pytest.raises(NmrError) as whole_bundle:
        load_input(root)
    assert whole_bundle.value.code == "INPUT_LIMIT"
    result = load_input(root, bruker_processing_numbers=[1])
    assert len(result["spectra"]) == 1 and len(result["originals"]) == 130
    assert (
        len(result["spectra"][0]["metadata"]["bruker_processing_selection"]["skipped_profiles"])
        == 64
    )


def test_processing_selection_project_persists_source_bytes_choice_and_replay(tmp_path):
    import hashlib
    import zipfile

    from nmr_companion.service import Service

    root = tmp_path / "source"
    originals = write_processing_selection_bundle(root)
    archive_path = tmp_path / "selected.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, data in originals.items():
            archive.writestr(name, data)
    expected = {"members/" + name: data for name, data in originals.items()}
    expected["archive/selected.zip"] = archive_path.read_bytes()
    service = Service(tmp_path / "selected.nmrproj")
    service.create("Synthetic explicit processing selection")
    command = {"op": "import", "path": str(archive_path), "bruker_processing_numbers": [1]}
    receipt = service.apply(0, "selected_import", command)
    project = service.read()
    assert project.revision == 1 and len(project.spectra) == 2
    assert any("not decoded or qualified" in warning for warning in receipt.warnings)
    with service.store.connection() as db:
        for name, data in expected.items():
            digest = hashlib.sha256(data).hexdigest()
            assert name in project.sources[digest].names
            assert (
                db.execute("SELECT data FROM originals WHERE sha256=?", (digest,)).fetchone()[0]
                == data
            )
    processed = next(s for s in project.spectra.values() if s.domain == "frequency")
    assert processed.metadata["bruker_processing_selection"]["skipped_profiles"] == [
        "members/run/pdata/700"
    ]
    bad_parameters = hashlib.sha256(expected["members/run/pdata/700/procs"]).hexdigest()
    assert bad_parameters not in processed.source_ids
    reopened = Service(service.store.path)
    assert reopened.read() == project
    assert reopened.apply(0, "selected_import", command).replayed
    with pytest.raises(NmrError) as different_selection:
        reopened.apply(0, "selected_import", {**command, "bruker_processing_numbers": [700]})
    assert different_selection.value.code == "REQUEST_ID_REUSED"
    assert reopened.read() == project
