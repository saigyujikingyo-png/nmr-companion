"""Bounded local readers preserving original bytes and processing stage.

Qualified: numeric single-block 1D JCAMP, CSV/TSV, complex Bruker 1D FID,
full-width Bruker 1D processed data, and a safe ZIP wrapper.
"""

from __future__ import annotations

import csv
import io
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import unicodedata
import warnings
import zipfile

import nmrglue as ng
import numpy as np

from .errors import NmrError

MAX_ORIGINAL_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_FILES = 1024
MAX_TRACES = 64
MAX_POINTS = 262144
MAX_ARCHIVE_RATIO = 200
_MAX_DEPTH = 16
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?")
_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", re.I)
_JCAMP_EXT = {".dx", ".jdx", ".jcamp"}


def _fail(code: str, message: str):
    raise NmrError(code, message)


def _safe_name(name: str) -> str:
    """Portable relative names prevent ZIP traversal and Windows aliasing."""
    if not name or len(name) > 512 or "\\" in name or name.startswith("/"):
        _fail("UNSAFE_INPUT", "An input name is not a safe relative path.")
    parts = name.split("/")
    if len(parts) > _MAX_DEPTH or any(
        p in {"", ".", ".."}
        or p.endswith((" ", "."))
        or _RESERVED.fullmatch(p)
        or any(ord(c) < 32 or c in ':<>"|?*' for c in p)
        for p in parts
    ):
        _fail("UNSAFE_INPUT", "An input name is not portable or escapes its root.")
    return name


def _is_link(st: os.stat_result) -> bool:
    return stat.S_ISLNK(st.st_mode) or bool(
        getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _read_file(path: Path) -> bytes:
    st = path.lstat()
    if _is_link(st) or not stat.S_ISREG(st.st_mode):
        _fail("UNSAFE_INPUT", "Input files must be regular files, without links.")
    if st.st_size > MAX_ORIGINAL_BYTES:
        _fail("INPUT_LIMIT", "An original file exceeds the 32 MiB limit.")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            st.st_dev,
            st.st_ino,
        ):
            _fail("INPUT_CHANGED", "An input changed while it was being captured.")
        data = stream.read(MAX_ORIGINAL_BYTES + 1)
        after = os.fstat(stream.fileno())
    if len(data) > MAX_ORIGINAL_BYTES:
        _fail("INPUT_LIMIT", "An original file exceeds the 32 MiB limit.")
    if len(data) != st.st_size or after.st_mtime_ns != st.st_mtime_ns:
        _fail("INPUT_CHANGED", "An input changed while it was being captured.")
    return data


def _check_bundle(files: dict[str, bytes], extra_bytes: int = 0) -> None:
    if len(files) > MAX_FILES:
        _fail("INPUT_LIMIT", "Input contains more than 1024 files.")
    total = extra_bytes
    seen: set[str] = set()
    for name, data in files.items():
        _safe_name(name)
        key = unicodedata.normalize("NFC", name).casefold()
        if key in seen:
            _fail("UNSAFE_INPUT", "Input contains duplicate or aliased file names.")
        seen.add(key)
        if len(data) > MAX_ORIGINAL_BYTES:
            _fail("INPUT_LIMIT", "An original file exceeds the 32 MiB limit.")
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            _fail("INPUT_LIMIT", "Total captured input exceeds 128 MiB.")
    for key in seen:
        parent = PurePosixPath(key).parent
        while str(parent) != ".":
            if str(parent) in seen:
                _fail("UNSAFE_INPUT", "An input file conflicts with a directory name.")
            parent = parent.parent


def _capture_directory(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    total = 0
    entries_seen = 0

    def walk(directory: Path, prefix: str = "", depth: int = 0) -> None:
        nonlocal total, entries_seen
        if depth > _MAX_DEPTH:
            _fail("INPUT_LIMIT", "Input directory nesting is too deep.")
        with os.scandir(directory) as entries:
            for entry in entries:
                entries_seen += 1
                if entries_seen > MAX_FILES:
                    _fail("INPUT_LIMIT", "Input contains more than 1024 entries.")
                name = _safe_name(prefix + entry.name)
                st = entry.stat(follow_symlinks=False)
                if _is_link(st):
                    _fail("UNSAFE_INPUT", "Input directories must not contain links.")
                if stat.S_ISDIR(st.st_mode):
                    walk(Path(entry.path), name + "/", depth + 1)
                elif stat.S_ISREG(st.st_mode):
                    data = _read_file(Path(entry.path))
                    total += len(data)
                    if total > MAX_TOTAL_BYTES:
                        _fail("INPUT_LIMIT", "Total captured input exceeds 128 MiB.")
                    files[name] = data
                else:
                    _fail("UNSAFE_INPUT", "Input contains a non-regular file.")

    walk(root)
    _check_bundle(files)
    return files


def _capture_zip(data: bytes) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    seen: set[str] = set()
    total = len(data)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_FILES:
                _fail("INPUT_LIMIT", "ZIP contains more than 1024 entries.")
            for info in infos:
                if "\x00" in info.orig_filename or "\\" in info.orig_filename:
                    _fail(
                        "UNSAFE_INPUT", "ZIP entry contains a null byte or nonportable separator."
                    )
                name = _safe_name(info.filename[:-1] if info.is_dir() else info.filename)
                key = unicodedata.normalize("NFC", name).casefold()
                if key in seen:
                    _fail("UNSAFE_INPUT", "ZIP contains duplicate or aliased names.")
                seen.add(key)
                kind = stat.S_IFMT(info.external_attr >> 16)
                if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                    _fail("UNSAFE_INPUT", "ZIP links and special files are not supported.")
                if kind == stat.S_IFDIR and not info.is_dir():
                    _fail("UNSAFE_INPUT", "ZIP directory metadata is inconsistent.")
                if info.flag_bits & 1 or info.compress_type not in (
                    zipfile.ZIP_STORED,
                    zipfile.ZIP_DEFLATED,
                ):
                    _fail(
                        "UNSUPPORTED_FORMAT",
                        "Encrypted or nonstandard ZIP compression is unsupported.",
                    )
                if info.is_dir():
                    continue
                if info.file_size > MAX_ORIGINAL_BYTES:
                    _fail("INPUT_LIMIT", "A ZIP member exceeds the 32 MiB limit.")
                total += info.file_size
                if total > MAX_TOTAL_BYTES:
                    _fail("INPUT_LIMIT", "Total captured ZIP input exceeds 128 MiB.")
                if info.file_size / max(info.compress_size, 1) > MAX_ARCHIVE_RATIO:
                    _fail("INPUT_LIMIT", "A ZIP member exceeds the compression-ratio limit.")
                with archive.open(info) as stream:
                    member = stream.read(MAX_ORIGINAL_BYTES + 1)
                if len(member) != info.file_size:
                    _fail("INVALID_FORMAT", "ZIP member length does not match its directory entry.")
                if PurePosixPath(name).suffix.lower() == ".zip":
                    _fail("UNSUPPORTED_FORMAT", "Nested ZIP archives are unsupported.")
                files[name] = member
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as exc:
        raise NmrError("INVALID_FORMAT", "ZIP is invalid, truncated or unsupported.") from exc
    _check_bundle(files, extra_bytes=len(data))
    return files


def _text(data: bytes) -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise NmrError("UNSUPPORTED_ENCODING", "Text input must use UTF-8 encoding.") from exc
    if "\x00" in text:
        _fail("INVALID_FORMAT", "Text input contains null bytes.")
    return text


def _float(value, label: str, *, positive: bool = False) -> float:
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise NmrError("INVALID_METADATA", f"{label} must be a finite number.") from exc
    if not math.isfinite(number) or (positive and number <= 0):
        _fail(
            "INVALID_METADATA", f"{label} must be finite" + (" and positive." if positive else ".")
        )
    return number


def _integer(value, label: str, minimum: int, maximum: int) -> int:
    value = _float(value, label)
    if not value.is_integer() or not minimum <= value <= maximum:
        _fail("INVALID_METADATA", f"{label} is outside its supported integer range.")
    return int(value)


def _nucleus(value) -> str | None:
    if value is None:
        return None
    label = re.sub(r"[\s^<>]", "", str(value))
    return label if re.fullmatch(r"\d{1,3}[A-Za-z]{1,2}", label) else None


def _spectrum(name, axis, real, imag, domain, nucleus, metadata) -> dict:
    x = np.asarray(axis, dtype=np.float64)
    y = np.asarray(real, dtype=np.float64)
    z = None if imag is None else np.asarray(imag, dtype=np.float64)
    if not 2 <= x.size <= MAX_POINTS or x.ndim != 1 or y.shape != x.shape:
        _fail("INVALID_DATA", "Spectrum dimensions are unsupported or inconsistent.")
    if z is not None and z.shape != x.shape:
        _fail("INVALID_DATA", "Real and imaginary data have different dimensions.")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        _fail("INVALID_DATA", "Spectrum contains non-finite values.")
    if z is not None and not np.isfinite(z).all():
        _fail("INVALID_DATA", "Spectrum contains non-finite values.")
    dx = np.diff(x)
    if not (np.all(dx > 0) or np.all(dx < 0)):
        _fail("INVALID_DATA", "Spectrum axis must be strictly monotonic.")
    return {
        "name": name,
        "axis": x.tolist(),
        "real": y.tolist(),
        "imag": None if z is None else z.tolist(),
        "axis_unit": "ppm" if domain == "frequency" else "s",
        "domain": domain,
        "nucleus": nucleus,
        "metadata": metadata,
    }


def _numbers(line: str) -> list[float]:
    # Strict AFFN: delimiters required; pseudodigits/packed signs fail explicitly.
    tokens = re.split(r"[\s,;]+", line.strip())
    if not tokens or any(not _NUMBER.fullmatch(token) for token in tokens):
        _fail(
            "UNSUPPORTED_ENCODING",
            "JCAMP requires delimited numeric AFFN data; compressed encodings are unsupported.",
        )
    return [_float(token, "JCAMP data") for token in tokens]


def _jcamp(name: str, data: bytes) -> dict:
    headers: dict[str, str] = {}
    datalines: list[str] = []
    active_key = None
    ended = False
    for raw in _text(data).splitlines():
        line = raw.split("$$", 1)[0].strip()
        if not line:
            continue
        if ended:
            _fail("UNSUPPORTED_FORMAT", "JCAMP must contain exactly one complete data block.")
        if line.startswith("##"):
            if "=" not in line:
                _fail("INVALID_FORMAT", "JCAMP label is missing an equals sign.")
            label, value = line[2:].split("=", 1)
            key = re.sub(r"[\s_/-]", "", label).upper()
            if key in headers:
                _fail("INVALID_FORMAT", "JCAMP contains a duplicate label or multiple blocks.")
            headers[key] = value.strip()
            active_key = key
            if key == "END":
                ended = True
        elif active_key in {"XYDATA", "XYPOINTS"}:
            datalines.append(line)
        elif active_key is not None:
            headers[active_key] += "\n" + line
        else:
            _fail("INVALID_FORMAT", "JCAMP data appears before its header.")
    if not ended or "TITLE" not in headers:
        _fail("INVALID_FORMAT", "JCAMP requires TITLE and END labels.")
    dtype = re.sub(r"\s", "", headers.get("DATATYPE", "")).upper()
    if (
        dtype not in {"NMRSPECTRUM", "NMRFID"}
        or any(key in headers for key in ("NTUPLES", "DATATABLE", "PAGE", "BLOCKS"))
        or headers.get("DATACLASS", "").upper() == "NTUPLES"
    ):
        _fail("UNSUPPORTED_FORMAT", "Only single-block 1D NMR JCAMP data is qualified.")
    modes = [key for key in ("XYDATA", "XYPOINTS") if key in headers]
    if len(modes) != 1 or not datalines:
        _fail("UNSUPPORTED_FORMAT", "JCAMP needs one numeric XYDATA or XYPOINTS section.")
    mode = modes[0]
    syntax = re.sub(r"\s", "", headers[mode]).upper()
    if (mode == "XYDATA" and syntax != "(X++(Y..Y))") or (
        mode == "XYPOINTS" and syntax != "(XY..XY)"
    ):
        _fail("UNSUPPORTED_ENCODING", "JCAMP data table syntax is not qualified.")
    count = _integer(headers.get("NPOINTS"), "NPOINTS", 2, MAX_POINTS)
    xf = _float(headers.get("XFACTOR", 1), "XFACTOR")
    yf = _float(headers.get("YFACTOR", 1), "YFACTOR")
    if xf == 0 or yf == 0:
        _fail("INVALID_METADATA", "JCAMP scale factors must not be zero.")
    first = _float(headers.get("FIRSTX"), "FIRSTX")
    last = _float(headers.get("LASTX"), "LASTX")
    step = (last - first) / (count - 1)
    if step == 0:
        _fail("INVALID_METADATA", "JCAMP FIRSTX and LASTX must differ.")
    tolerance = max(abs(step) * 1e-5, 1e-10)
    if "DELTAX" in headers and not math.isclose(
        _float(headers["DELTAX"], "DELTAX"), step, rel_tol=1e-5, abs_tol=1e-10
    ):
        _fail("INVALID_METADATA", "JCAMP DELTAX disagrees with its axis endpoints.")
    real: list[float] = []
    axis: list[float] = []
    for line in datalines:
        values = _numbers(line)
        if mode == "XYDATA":
            if len(values) < 2 or abs(values[0] * xf - (first + len(real) * step)) > tolerance:
                _fail("INVALID_DATA", "JCAMP row anchor does not match the declared regular axis.")
            real.extend(v * yf for v in values[1:])
        else:
            if len(values) % 2:
                _fail("INVALID_DATA", "JCAMP XYPOINTS must contain complete coordinate pairs.")
            axis.extend(v * xf for v in values[::2])
            real.extend(v * yf for v in values[1::2])
        if len(real) > count:
            _fail("INVALID_DATA", "JCAMP contains more values than NPOINTS.")
    if len(real) != count:
        _fail("INVALID_DATA", "JCAMP value count does not match NPOINTS.")
    if mode == "XYDATA":
        axis = np.linspace(first, last, count).tolist()
    elif abs(axis[0] - first) > tolerance or abs(axis[-1] - last) > tolerance:
        _fail("INVALID_DATA", "JCAMP coordinates disagree with FIRSTX/LASTX.")
    unit = headers.get("XUNITS", "").strip().upper()
    metadata = {
        "format": "jcamp-dx",
        "reader": "nmr-companion.affn.v1",
        "source_name": name,
        "source_title": headers["TITLE"],
        "encoding": "AFFN",
        "signed_values_preserved": True,
        "data_type": dtype,
        "y_units": headers.get("YUNITS", "unknown"),
        "original_x_units": unit,
        "x_factor": xf,
        "y_factor": yf,
    }
    if dtype == "NMRSPECTRUM":
        if unit != "PPM":
            _fail(
                "UNSUPPORTED_UNITS",
                "Frequency JCAMP requires an explicit ppm axis; Hz referencing is not inferred.",
            )
        domain = "frequency"
        metadata.update(stage="processed_spectrum", fft_applied_on_import=False)
    else:
        factors = {"S": 1, "SECONDS": 1, "SECOND": 1, "MS": 0.001, "US": 0.000001}
        if unit not in factors:
            _fail("UNSUPPORTED_UNITS", "FID JCAMP needs an explicit s, ms or us time axis.")
        axis = [v * factors[unit] for v in axis]
        if axis[0] < 0 or any(b <= a for a, b in zip(axis, axis[1:])):
            _fail("INVALID_DATA", "FID time coordinates must be nonnegative and increasing.")
        domain = "time"
        metadata.update(stage="raw_fid_real_only", complex_processing_ready=False)
    nucleus = _nucleus(headers.get(".OBSERVENUCLEUS"))
    return _spectrum(name, axis, real, None, domain, nucleus, metadata)


def _table(name: str, data: bytes) -> dict:
    text = _text(data)
    try:
        if PurePosixPath(name).suffix.lower() == ".tsv":
            delimiter = "\t"
        else:
            try:
                delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",;\t").delimiter
            except csv.Error:
                delimiter = ","
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        try:
            columns = [column.strip() for column in next(reader)]
        except StopIteration:
            _fail("INVALID_FORMAT", "CSV is empty.")
        if not 1 <= len(columns) <= 64 or any(not x or len(x) > 256 for x in columns):
            _fail("INVALID_FORMAT", "CSV needs 1 to 64 nonempty, bounded column names.")
        if len(set(columns)) != len(columns):
            _fail("INVALID_FORMAT", "CSV column names must be unique.")
        rows = []
        for values in reader:
            if not values:
                continue
            if len(values) != len(columns):
                _fail("INVALID_FORMAT", "CSV row width does not match its header.")
            if len(rows) >= MAX_POINTS:
                _fail("INPUT_LIMIT", "CSV exceeds the supported row count.")
            rows.append(dict(zip(columns, values, strict=True)))
        if not rows:
            _fail("INVALID_FORMAT", "CSV contains no data rows.")
    except csv.Error as exc:
        raise NmrError("INVALID_FORMAT", "CSV quoting or field size is invalid.") from exc
    return {"name": name, "columns": columns, "rows": rows}


def _parameters(data: bytes, names: set[str]) -> dict:
    # Upstream's general parameter reader can wait forever for truncated arrays.
    # Only bounded single-line scalars needed by our qualified profiles are read.
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252")
    result = {}
    for line in text.splitlines():
        match = re.match(r"##\$([^=]+)=(.*)", line)
        if match is None or match[1].strip() not in names:
            continue
        key = match[1].strip()
        if key in result:
            _fail("INVALID_METADATA", "Bruker contains duplicate required metadata.")
        value = match[2].split("$$", 1)[0].strip()
        if value.startswith("<"):
            if not value.endswith(">"):
                _fail("INVALID_METADATA", "A required Bruker string is truncated.")
            value = value[1:-1]
        result[key] = value
    return result


def _bruker_raw(name: str, files: dict[str, bytes], temp: Path) -> dict:
    parent = str(PurePosixPath(name).parent)
    prefix = "" if parent == "." else parent + "/"
    param_name = prefix + "acqus"
    if param_name not in files:
        _fail("INVALID_METADATA", "Bruker fid requires its sibling acqus file.")
    if any(prefix + f"acqu{i}s" in files for i in (2, 3, 4)):
        _fail("UNSUPPORTED_FORMAT", "Multidimensional Bruker raw acquisition is not qualified.")
    names = {
        "TD",
        "DTYPA",
        "BYTORDA",
        "AQ_mod",
        "SW_h",
        "SFO1",
        "O1",
        "NUC1",
        "GRPDLY",
        "DSPFVS",
        "DECIM",
        "FnTYPE",
        "BF1",
    }
    p = _parameters(files[param_name], names)
    td = _integer(p.get("TD"), "TD", 4, MAX_POINTS * 2)
    mode = _integer(p.get("AQ_mod"), "AQ_mod", 0, 3)
    if mode not in (1, 3) or td % 2:
        _fail("UNSUPPORTED_FORMAT", "Bruker raw requires even TD and complex AQ_mod 1 or 3.")
    if "FnTYPE" in p and _integer(p["FnTYPE"], "FnTYPE", 0, 2) == 2:
        _fail("UNSUPPORTED_FORMAT", "Nonuniformly sampled Bruker data is not qualified.")
    dtype = _integer(p.get("DTYPA"), "DTYPA", 0, 2)
    if dtype not in (0, 2):
        _fail("UNSUPPORTED_FORMAT", "Only int32 and float64 Bruker raw data are supported.")
    endian = _integer(p.get("BYTORDA"), "BYTORDA", 0, 1)
    width = 8 if dtype == 2 else 4
    expected = td * width
    padded = math.ceil(expected / 1024) * 1024
    if len(files[name]) not in (expected, padded):
        _fail("INVALID_DATA", "Bruker fid size disagrees with TD and storage padding.")
    sw = _float(p.get("SW_h"), "SW_h", positive=True)
    obs = _float(p.get("SFO1"), "SFO1", positive=True)
    offset = _float(p.get("O1"), "O1")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _, values = ng.bruker.read_binary(
            str(temp.joinpath(*PurePosixPath(name).parts)),
            shape=(len(files[name]) // width // 2,),
            cplex=True,
            big=bool(endian),
            isfloat=dtype == 2,
        )
    values = values[: td // 2].astype(np.complex128)
    if not np.isfinite(values).all():
        _fail("INVALID_DATA", "Bruker raw contains non-finite values.")
    delay = _float(p["GRPDLY"], "GRPDLY") if "GRPDLY" in p else None
    correction = {"applied": False, "method": "none", "points_before": values.size}
    if delay is None or delay < 0:
        firmware = _integer(p.get("DSPFVS"), "DSPFVS", 0, 100)
        decim = _integer(p.get("DECIM"), "DECIM", 1, 100000)
        if firmware >= 14:
            _fail(
                "UNRESOLVED_FILTER", "This Bruker firmware requires an explicit nonnegative GRPDLY."
            )
        try:
            delay = float(ng.bruker.bruker_dsp_table[firmware][decim])
        except KeyError as exc:
            raise NmrError(
                "UNRESOLVED_FILTER",
                "Digital-filter delay is absent from the qualified lookup table.",
            ) from exc
        correction["delay_source"] = "nmrglue.DSPFVS_DECIM_table"
    else:
        correction["delay_source"] = "GRPDLY"
    if delay > 0:
        # Upstream also removes two points for zero delay; skip it when delay is zero.
        if math.floor(delay) + 2 >= values.size - 1:
            _fail("INVALID_DATA", "FID is too short for its declared digital-filter delay.")
        values = ng.bruker.rm_dig_filter(values, 0, 0, grpdly=delay, truncate_grpdly=True)
        correction.update(
            applied=True,
            method="nmrglue.bruker.rm_dig_filter",
            truncate_grpdly=True,
            post_proc=False,
        )
    correction["points_after"] = values.size
    metadata = {
        "format": "bruker",
        "reader": "nmrglue",
        "reader_version": ng.__version__,
        "source_name": name,
        "stage": "raw_fid",
        "dwell_s": 1 / sw,
        "obs_mhz": obs,
        "carrier_ppm": offset / obs,
        "group_delay": delay,
        "digital_filter": correction,
        "fft_applied_on_import": False,
        "complex_processing_ready": True,
        "signed_values_preserved": True,
        "reference_convention": "O1/SFO1; acquisition reference, without processed SR correction",
        "TD": td,
        "AQ_mod": mode,
        "DTYPA": dtype,
        "BYTORDA": endian,
        "storage_padding_bytes": len(files[name]) - expected,
    }
    return _spectrum(
        name,
        np.arange(values.size) / sw,
        values.real,
        values.imag,
        "time",
        _nucleus(p.get("NUC1")),
        metadata,
    )


def _bruker_processed(name: str, files: dict[str, bytes], temp: Path) -> dict:
    directory = PurePosixPath(name).parent
    prefix = "" if str(directory) == "." else str(directory) + "/"
    param_name = prefix + "procs"
    if param_name not in files:
        _fail("INVALID_METADATA", "Bruker 1r requires its sibling procs file.")
    if any(prefix + f"proc{i}s" in files for i in (2, 3, 4)):
        _fail("UNSUPPORTED_FORMAT", "Multidimensional processed Bruker data is not qualified.")
    p = _parameters(
        files[param_name],
        {
            "SI",
            "SF",
            "SW_p",
            "OFFSET",
            "BYTORDP",
            "DTYPP",
            "NC_proc",
            "AXNUC",
            "STSI",
            "STSR",
            "PHC0",
            "PHC1",
        },
    )
    count = _integer(p.get("SI"), "SI", 2, MAX_POINTS)
    if ("STSR" in p and _integer(p["STSR"], "STSR", 0, MAX_POINTS) != 0) or (
        "STSI" in p and _integer(p["STSI"], "STSI", 0, MAX_POINTS) not in (0, count)
    ):
        _fail("UNSUPPORTED_FORMAT", "Cropped Bruker processed axes are not qualified.")
    obs = _float(p.get("SF"), "SF", positive=True)
    sw = _float(p.get("SW_p"), "SW_p", positive=True)
    offset = _float(p.get("OFFSET"), "OFFSET")
    endian = _integer(p.get("BYTORDP"), "BYTORDP", 0, 1)
    dtype = _integer(p.get("DTYPP"), "DTYPP", 0, 2)
    if dtype not in (0, 2):
        _fail("UNSUPPORTED_FORMAT", "Only int32 and float64 processed Bruker data are supported.")
    exponent = _integer(p.get("NC_proc"), "NC_proc", -256, 256)
    expected = count * (8 if dtype == 2 else 4)

    def component(component_name: str):
        if len(files[component_name]) != expected:
            _fail("INVALID_DATA", "Bruker processed component size disagrees with SI.")
        _, values = ng.bruker.read_pdata_binary(
            str(temp.joinpath(*PurePosixPath(component_name).parts)),
            shape=(count,),
            submatrix_shape=(count,),
            big=bool(endian),
            isfloat=dtype == 2,
        )
        return np.asarray(values, dtype=np.float64) * (2.0**exponent)

    real = component(name)
    imag_name = prefix + "1i"
    imag = component(imag_name) if imag_name in files else None
    nucleus = _nucleus(p.get("AXNUC"))
    acquisition = str(directory.parent.parent / "acqus")
    if nucleus is None and acquisition in files:
        nucleus = _nucleus(_parameters(files[acquisition], {"NUC1"}).get("NUC1"))
    metadata = {
        "format": "bruker",
        "reader": "nmrglue",
        "reader_version": ng.__version__,
        "source_name": name,
        "stage": "processed_spectrum",
        "fft_applied_on_import": False,
        "digital_filter": {"applied": False, "method": "not_applicable_processed_input"},
        "obs_mhz": obs,
        "spectral_width_hz": sw,
        "SI": count,
        "NC_proc": exponent,
        "scale_applied": "stored_value * 2**NC_proc",
        "signed_values_preserved": True,
        "reference_convention": "OFFSET - point_index * SW_p / (SI * SF)",
        "complex_processing_ready": imag is not None,
    }
    for field in ("PHC0", "PHC1"):
        if field in p:
            metadata["source_" + field] = _float(p[field], field)
    axis = offset - np.arange(count) * sw / (count * obs)
    return _spectrum(name, axis, real, imag, "frequency", nucleus, metadata)


def _interpret(files: dict[str, bytes]) -> dict:
    result = {"spectra": [], "grids": [], "tables": [], "originals": [], "warnings": []}
    if not files:
        _fail("INVALID_FORMAT", "Input contains no files.")
    if any(PurePosixPath(name).name in {"ser", "2rr", "3rrr", "4rrrr"} for name in files):
        _fail(
            "UNSUPPORTED_FORMAT", "Raw or processed multidimensional Bruker data is not qualified."
        )
    readers = []
    for name in sorted(files):
        leaf = PurePosixPath(name).name
        suffix = PurePosixPath(name).suffix.lower()
        if suffix in _JCAMP_EXT:
            readers.append(("spectrum", name, _jcamp))
        elif suffix in {".csv", ".tsv"}:
            readers.append(("table", name, _table))
        elif leaf == "fid":
            readers.append(("bruker", name, _bruker_raw))
        elif leaf == "1r":
            readers.append(("bruker", name, _bruker_processed))
    if len(readers) > MAX_TRACES:
        _fail("INPUT_LIMIT", "Input contains more than 64 supported traces/tables.")
    if not readers:
        _fail("UNSUPPORTED_FORMAT", "No qualified JCAMP, CSV or Bruker 1D data was found.")
    with tempfile.TemporaryDirectory(prefix="nmr-import-") as temp_dir:
        temp = Path(temp_dir)
        if any(kind == "bruker" for kind, _, _ in readers):
            for name, data in files.items():
                destination = temp.joinpath(*PurePosixPath(name).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
        for kind, name, reader in readers:
            value = reader(name, files, temp) if kind == "bruker" else reader(name, files[name])
            if kind == "table":
                result["tables"].append(value)
            else:
                result["spectra"].append(value)
                if value["nucleus"] is None:
                    result["warnings"].append(
                        f"Nucleus is unknown for {name}; no nucleus was inferred."
                    )
    result["originals"] = [{"name": name, "data": data} for name, data in sorted(files.items())]
    if result["tables"]:
        result["warnings"].append(
            "CSV rows are preserved as text; trace pairing, time units and echo-time basis require explicit mapping."
        )
    if any(s["metadata"].get("stage") == "raw_fid_real_only" for s in result["spectra"]):
        result["warnings"].append(
            "Real-only JCAMP FIDs lack a qualified complex-processing profile."
        )
    return result


def load_input(path: str | Path) -> dict:
    """Return validated stage-aware data plus original file and archive bytes.

    Errors are bounded NmrError messages, not tracebacks or absolute paths.
    """
    try:
        source = Path(path).expanduser()
        st = source.lstat()
        if _is_link(st):
            _fail("UNSAFE_INPUT", "Input root must not be a symbolic link or reparse point.")
        container = None
        if stat.S_ISDIR(st.st_mode):
            files = _capture_directory(source)
        elif stat.S_ISREG(st.st_mode):
            name = _safe_name(source.name)
            data = _read_file(source)
            if source.suffix.lower() == ".zip":
                files = _capture_zip(data)
                container = {"name": "archive/" + name, "data": data}
            else:
                files = {name: data}
                _check_bundle(files)
        else:
            _fail("UNSAFE_INPUT", "Input must be a regular file or directory.")
        result = _interpret(files)
        if container:
            for item in result["originals"]:
                item["name"] = "members/" + item["name"]
            for spectrum in result["spectra"]:
                spectrum["metadata"]["source_name"] = (
                    "members/" + spectrum["metadata"]["source_name"]
                )
            result["originals"].insert(0, container)
        return result
    except NmrError:
        raise
    except (OSError, ValueError, TypeError, OverflowError, Warning, zipfile.LargeZipFile) as exc:
        raise NmrError(
            "IMPORT_FAILED",
            "Input could not be read with its declared format; check metadata and completeness.",
        ) from exc
