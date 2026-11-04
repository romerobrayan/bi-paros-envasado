"""Read Excel *tables* (ListObjects) by name from an .xlsm without running macros.

openpyxl in read-only mode is fast but does not expose table definitions, so we
read the table XML parts from the zip package to get each table's sheet and
range, then stream only that range with openpyxl (cached formula values).
"""
from __future__ import annotations

import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET

import openpyxl
import pandas as pd
from openpyxl.utils.cell import range_boundaries

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def _rels(z: zipfile.ZipFile, part: str) -> dict[str, str]:
    """Return {rId: absolute target part} for a package part."""
    folder, name = posixpath.split(part)
    rels_part = posixpath.join(folder, "_rels", name + ".rels")
    if rels_part not in z.namelist():
        return {}
    root = ET.fromstring(z.read(rels_part))
    out = {}
    for rel in root.findall("rel:Relationship", NS):
        target = rel.attrib["Target"]
        target = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
        out[rel.attrib["Id"]] = target
    return out


def table_index(path: str) -> dict[str, tuple[str, str]]:
    """Map table name -> (sheet name, A1 range)."""
    with zipfile.ZipFile(path) as z:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        wb_rels = _rels(z, "xl/workbook.xml")
        index: dict[str, tuple[str, str]] = {}
        for sheet in wb.find("m:sheets", NS):
            sheet_name = sheet.attrib["name"]
            sheet_part = wb_rels[sheet.attrib[f"{{{NS['r']}}}id"]]
            for target in _rels(z, sheet_part).values():
                if "/tables/" in target:
                    t = ET.fromstring(z.read(target))
                    index[t.attrib["name"]] = (sheet_name, t.attrib["ref"])
        return index


class ExcelTables:
    """Lazy reader for named tables of one workbook."""

    def __init__(self, path: str):
        self.path = path
        self.index = table_index(path)
        self._wb = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_vba=False)

    def read(self, name: str) -> pd.DataFrame:
        sheet, ref = self.index[name]
        min_col, min_row, max_col, max_row = range_boundaries(ref)
        rows = list(self._wb[sheet].iter_rows(min_row=min_row, max_row=max_row,
                                              min_col=min_col, max_col=max_col, values_only=True))
        header = [re.sub(r"\s+", " ", str(h)).strip() if h is not None else f"col{i}"
                  for i, h in enumerate(rows[0])]
        df = pd.DataFrame(rows[1:], columns=header)
        # Excel row number of each data row (lineage)
        df.insert(0, "source_row", range(min_row + 1, min_row + 1 + len(df)))
        return df

    def close(self) -> None:
        self._wb.close()
