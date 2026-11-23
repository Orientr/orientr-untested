# Copyright (C) 2026 Wouter Carleer. Licensed under the GNU General Public License version 3, see LICENSE.
"""The slicer-independent part of Orientr: the SOMA model (its printable parts as meshes), the geometry, the
orientation of each part, the rules for support, brim, walls and infill, and packing the parts onto plates.

The rules write their choices as Bambu Studio setting names (enable_support, brim_width, wall_loops, ...), the only
slicer so far; the printer (`t`) is anything with the attributes of bambu_project.Template (bed, zones, nozzles).
Nothing here starts or reads a slicer. orientr.py is the app, bambu_project.py the Bambu Studio part.
"""
from __future__ import annotations

import colorsys
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

# scipy is imported inside the geometry functions: --status and --models then start faster

# --- rules (mm, mm2, degrees) -------------------------------------------------------------------------------------
LIFT = 0.2                # overhang triangles lower than this above the bed are ignored (first layer)


SPOT_AREA = 10.0          # anchored overhang regions smaller than this are ignored (hole tops, chamfer rims)


ISLAND_AREA = 1.0         # unanchored regions (nothing below them) need support from this size on


LEDGE_DEPTH = 1.0         # anchored regions sticking out at most this far (area / held edge length) print fine


BED_RIM_REACH = 1.0       # a region growing out of the first layer (rounded or chamfered bottom edge) that reaches at


                          # most this far past the first layer's outline (sliced at half the first layer) prints fine;
                          # too low for support anyway. 30 deg threshold, 0.2 mm first layer: reach =
                          # r * (sin 30 - sin(acos(1 - 0.1 / r))), so a bottom fillet up to about R3.7 (tested on bars:
                          # R3.5 ignored, R4 support). 2026-11-18, after Bambu warned about a bottom fillet
BRIDGE_NZ = -0.98         # a region this flat, held by material below on both sides ...


BRIDGE_SPAN = 10.0        # ... and at most this wide prints as a bridge without support


ANCHOR_END = 0.25         # "both sides": anchored edges within this fraction of the span from each end


SUPPORT_REGION = 20.0     # support on if one remaining region is at least this large ...


SUPPORT_TOTAL = 50.0      # ... or all remaining regions together


DESIGN_OVERHANG = 45.0    # SOMA's design rule (from vertical), reported as a warning only


W_BED, W_HEIGHT = 0.3, 0.1  # cost = (A_over - W_BED * A_bed) / A_surface + W_HEIGHT * H / largest size


KEEP_MODELLED = 0.02      # the modelled orientation wins if its cost is within this of the best


STRENGTH_TILT = 15.0      # loaded parts: the load axis may leave the layers by at most this (layers are the weak way)


BRIM_SLENDER = (2.5, 5.0)   # height of the centre of mass / its distance to the contact edge -> brim 5 / 8 mm


BRIM_CONTACT = (80.0, 30.0)  # bed contact below this -> brim 5 / 8 mm


BRIM_WIDTH = (5.0, 8.0)


INFILL_LINKED = ("skeleton_infill_density", "skin_infill_density")   # Bambu Studio sets these with the infill


FULL_INFILL_PATTERN = "zig-zag"  # 100 % infill needs this pattern ("Rectilinear" in the window): grid, gyroid and


                                 # monotonic fail the slice with error -18 (tested 2026-11-18); the window asks to
                                 # switch to it too ("Grid infill pattern doesn't support 100% density")
WARP_MATERIALS = ("ABS", "ASA", "PC", "PA", "PET-CF", "PA-CF", "PAHT")


WARP_LENGTH = 100.0       # warping materials: brim when the footprint is longer than this


WARP_SMALL = (150.0, 30.0)  # warping materials: brim for small parts too, bed contact (mm2) or footprint (mm) below


                            # this: they come loose or curl up at the corners (2026-11-18)
WARP_BED_TEMP = 90.0      # a filament whose profile wants a bed this hot (or a heated chamber) tends to warp


TINY_SIDE, TINY_VOLUME = 15.0, 1000.0


FUNCTION_SETTINGS = {
    "snap": {"wall_loops": "4", "sparse_infill_density": "40%"},
    "spring": {"wall_loops": "4", "sparse_infill_density": "40%"},
    "load": {"wall_loops": "4", "sparse_infill_density": "30%"},
}


GAP = 6.0                 # between parts on the plate (plus their brims)


# Tree support spreads at its foot beyond the part's outline: a test part's cap 9.6 mm (measured in Bambu Studio's G-code,
# 2026-11-19). 6 mm (GAP) to a neighbour failed the slice ("G-code conflicts", code -101), 10 mm sliced. A part with
# support keeps this much extra room around it, like a brim (the larger of the two counts: the brim lies under it),
# so a neighbour is at least GAP + SUPPORT_ROOM = 11 mm away. 10 mm extra cost the 10-part test model a second plate.
SUPPORT_ROOM = 5.0


MARGIN = 5.0              # from the edge of the usable bed


PLATE_GAP = 0.2           # Bambu Studio's gap between plates, as a fraction of the bed size


AXES = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}


COLOR_NAMES = {
    "black": (0.08, 0.08, 0.08), "white": (0.93, 0.93, 0.92), "grey": (0.55, 0.55, 0.57), "red": (0.78, 0.07, 0.06),
    "orange": (0.95, 0.45, 0.05), "yellow": (0.95, 0.78, 0.10), "green": (0.15, 0.6, 0.2), "blue": (0.1, 0.3, 0.8),
    "brown": (0.45, 0.28, 0.12), "purple": (0.5, 0.2, 0.6), "pink": (0.9, 0.7, 0.8), "dark grey": (0.3, 0.3, 0.3),
}


TOOL_DIR = Path(__file__).resolve().parent


if str(TOOL_DIR) not in sys.path:                         # python -I leaves the script's folder out: the form,
    sys.path.insert(0, str(TOOL_DIR))                     # the texts and the menu helpers live next to this file


from orientr_i18n import APP_DIR, t as tr                   # noqa: E402  (needs TOOL_DIR on sys.path)


TEMP_PREFIX = "orientr-"   # every temporary file and folder of the tool, so that clean_old_temp knows them


def orientr_tempdir(kind: str = "run") -> tempfile.TemporaryDirectory:
    """A temporary folder of the tool (%TEMP%\\orientr-<kind>-...). Removed afterwards; a file Bambu Studio still holds
    leaves it behind, and clean_old_temp removes it later."""
    return tempfile.TemporaryDirectory(prefix=f"{TEMP_PREFIX}{kind}-", ignore_cleanup_errors=True)


def clean_old_temp(days: float = 1) -> None:
    """Remove the tool's temporary files and folders older than `days` (2026-11-22: an interrupted run, or a file
    still open in Bambu Studio, left them in %TEMP% for good). Only names starting with TEMP_PREFIX, and only old
    ones, so a run going on at the same time keeps its own."""
    cutoff = time.time() - days * 86400
    for item in Path(tempfile.gettempdir()).glob(TEMP_PREFIX + "*"):
        try:
            if item.stat().st_mtime < cutoff:
                shutil.rmtree(item, ignore_errors=True) if item.is_dir() else item.unlink()
        except OSError:
            pass


class ToolError(Exception):
    """A problem the user has to fix (shown without a traceback)."""


# --- mesh ---------------------------------------------------------------------------------------------------------
def read_stl(path: Path) -> np.ndarray:
    """Triangles (n, 3, 3) from a binary or ASCII STL."""
    data = path.read_bytes()
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if len(data) == 84 + 50 * n:
            rec = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]),
                                count=n, offset=84)
            return rec["v"].astype(np.float64)
    nums = re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data)
    if not nums:
        raise ToolError(tr("e.stl", file=path.name))
    return np.array(nums, dtype=np.float64).reshape(-1, 3, 3)


@dataclass
class Mesh:
    verts: np.ndarray   # (v, 3)
    faces: np.ndarray   # (f, 3) int
    mate: np.ndarray = None    # per edge (3 per face, edge k of face f = 3f+k): the same edge in the neighbour, or -1

    @classmethod
    def from_triangles(cls, tris: np.ndarray, name: str = "part") -> "Mesh":
        pts = tris.reshape(-1, 3)
        key = np.round(pts, 4)
        uniq, inv = np.unique(key, axis=0, return_inverse=True)
        faces = inv.reshape(-1, 3)
        # drop degenerate triangles (merged corners or zero area), then the vertices nobody uses any more
        t = uniq[faces]
        area2 = np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1)
        ok = ((faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
              & (area2 > 1e-10))
        faces = faces[ok]
        used, compact = np.unique(faces, return_inverse=True)
        m = cls(uniq[used], compact.reshape(-1, 3))
        if len(m.faces) < 4 or m.volume() < 1e-6:
            raise ToolError(tr("e.mesh_empty", name=name))
        m.mate = m._edge_mates()
        return m

    def edges(self) -> np.ndarray:
        """Edge k of face f (k = 0, 1, 2) runs from vertex k to vertex k+1; shape (3f, 2)."""
        return np.stack([self.faces, np.roll(self.faces, -1, axis=1)], axis=2).reshape(-1, 2)

    def _edge_mates(self) -> np.ndarray:
        e = np.sort(self.edges(), axis=1)
        key = e[:, 0].astype(np.int64) * len(self.verts) + e[:, 1]
        order = np.argsort(key, kind="stable")
        ks = key[order]
        same = ks[1:] == ks[:-1]
        mate = np.full(len(e), -1)
        i, j = order[:-1][same], order[1:][same]
        mate[i], mate[j] = j, i
        return mate

    def transformed(self, rot: np.ndarray) -> "Mesh":
        return Mesh(self.verts @ rot.T, self.faces, self.mate)

    def volume(self) -> float:
        a, b, c = (self.verts[self.faces[:, i]] for i in range(3))
        return abs(float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6.0)

    def centre_of_mass(self) -> np.ndarray:
        a, b, c = (self.verts[self.faces[:, i]] for i in range(3))
        v6 = np.einsum("ij,ij->i", a, np.cross(b, c))
        return (v6[:, None] * (a + b + c)).sum(axis=0) / (4 * v6.sum())


def rotation_to_down(d) -> np.ndarray:
    """Rotation matrix that turns direction d into -Z."""
    a = np.asarray(d, float)
    a = a / np.linalg.norm(a)
    b = np.array([0.0, 0.0, -1.0])
    c = float(a @ b)
    if c > 1 - 1e-9:
        return np.eye(3)
    if c < -1 + 1e-9:                      # d is +Z: half turn about X
        return np.diag([1.0, -1.0, -1.0])
    v = np.cross(a, b)
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx / (1 + c)


def hull_of(points2d: np.ndarray) -> np.ndarray | None:
    """Convex hull corners (counter-clockwise) of 2D points, or None for fewer than 3 or collinear points."""
    from scipy.spatial import ConvexHull, QhullError
    pts = np.unique(np.round(points2d, 4), axis=0)
    if len(pts) < 3:
        return None
    try:
        return pts[ConvexHull(pts).vertices]
    except QhullError:
        return None


def min_width(points2d: np.ndarray) -> tuple[float, np.ndarray]:
    """Smallest width of the convex hull of 2D points and the unit direction across it (rotating calipers)."""
    hull = hull_of(points2d)
    if hull is None:                                  # a point or a line: no width
        pts = np.asarray(points2d, float).reshape(-1, 2)
        d = pts.max(axis=0) - pts.min(axis=0) if len(pts) else np.array([1.0, 0.0])
        n = np.array([-d[1], d[0]])
        return 0.0, n / np.linalg.norm(n) if np.linalg.norm(n) > 0 else np.array([1.0, 0.0])
    best, across = math.inf, np.array([1.0, 0.0])
    for i in range(len(hull)):
        e = hull[(i + 1) % len(hull)] - hull[i]
        ln = math.hypot(*e)
        if ln < 1e-9:
            continue
        nrm = np.array([-e[1], e[0]]) / ln
        w = float(np.max(np.abs((hull - hull[i]) @ nrm)))
        if w < best:
            best, across = w, nrm
    return best, across


def inside_distance(hull: np.ndarray | None, p: np.ndarray) -> float:
    """Distance from p to the nearest edge of a counter-clockwise hull, negative when p lies outside."""
    if hull is None:
        return 0.0
    e = np.roll(hull, -1, axis=0) - hull
    ln = np.linalg.norm(e, axis=1)
    keep = ln > 1e-9
    inward = np.stack([-e[keep, 1], e[keep, 0]], axis=1) / ln[keep, None]
    return float(np.min(np.einsum("ij,ij->i", p - hull[keep], inward)))


def dist_to_segments(p: np.ndarray, a: np.ndarray, b: np.ndarray, cells: int = 1_000_000) -> np.ndarray:
    """Distance from each 2D point p to the nearest of the segments a-b, in chunks of points sized so that one chunk
    holds at most `cells` point-segment pairs (bounded memory, also for a very detailed outline)."""
    ab = b - a
    ll = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18)
    out = np.empty(len(p))
    chunk = max(1, cells // max(len(a), 1))
    for i in range(0, len(p), chunk):
        q = p[i:i + chunk, None, :] - a[None]                      # (n, k, 2)
        t = np.clip(np.einsum("nkj,kj->nk", q, ab) / ll, 0.0, 1.0)
        d = q - t[:, :, None] * ab[None]
        out[i:i + chunk] = np.sqrt(np.einsum("nkj,nkj->nk", d, d).min(axis=1))
    return out


def tri_samples(t: np.ndarray, step: float = 0.3) -> np.ndarray:
    """2D points covering triangles t (n, 3, 2) at most `step` apart along the edges: corners, edges and inside, so a
    distance measured at these points cannot miss a large triangle's middle (off by at most about step / 2)."""
    e = np.linalg.norm(t - np.roll(t, -1, axis=1), axis=2).max(axis=1)
    k = np.clip(np.ceil(e / step), 1, 64).astype(int)
    out = []
    for s in np.unique(k):
        i, j = np.meshgrid(np.arange(s + 1), np.arange(s + 1), indexing="ij")
        keep = (i + j) <= s
        w = np.stack([i[keep], j[keep], s - i[keep] - j[keep]], axis=1) / s      # barycentric weights
        out.append(np.einsum("pw,nwd->npd", w, t[k == s]).reshape(-1, 2))
    return np.vstack(out) if out else np.zeros((0, 2))


def cross_section(tri: np.ndarray, normals: np.ndarray, z0: float) -> tuple[float, np.ndarray]:
    """Area and outline points of the solid's cross-section at height z0.

    Every cut segment is oriented along z x n (counter-clockwise around material), so the shoelace sum over all
    segments gives the area without joining them into loops; holes come out negative by themselves."""
    z = tri[:, :, 2] - z0
    below = z < 0                      # a vertex exactly on the plane counts as above: always two crossing edges
    cut = below.any(axis=1) & ~below.all(axis=1)
    if not cut.any():
        return 0.0, np.zeros((0, 2))
    t, zz, n, bl = tri[cut], z[cut], normals[cut], below[cut]
    a, b = t, np.roll(t, -1, axis=1)
    za, zb = zz, np.roll(zz, -1, axis=1)
    hit = bl != np.roll(bl, -1, axis=1)
    s = np.where(hit, za / np.where(hit, za - zb, 1.0), 0.0)
    pts = (a + (b - a) * s[:, :, None])[:, :, :2]
    first = np.argsort(~hit, axis=1, kind="stable")[:, :2]   # the two edges that cross z0
    rows = np.arange(len(t))
    p1, p2 = pts[rows, first[:, 0]], pts[rows, first[:, 1]]
    tangent = np.stack([-n[:, 1], n[:, 0]], axis=1)
    flip = np.einsum("ij,ij->i", p2 - p1, tangent) < 0
    p1[flip], p2[flip] = p2[flip].copy(), p1[flip].copy()
    area = 0.5 * float(np.sum(p1[:, 0] * p2[:, 1] - p2[:, 0] * p1[:, 1]))
    return area, np.vstack([p1, p2])


def components(faces: np.ndarray, nverts: int) -> np.ndarray:
    """Connected regions of triangles that share a vertex; label per triangle."""
    m = len(faces)
    if m == 0:
        return np.zeros(0, int)
    rows = np.repeat(np.arange(m), 3)
    cols = m + faces.reshape(-1)
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components
    g = csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(m + nverts, m + nverts))
    _, labels = connected_components(g, directed=False)
    return labels[:m]


@dataclass
class Analysis:
    rot: np.ndarray
    down: str
    height: float
    size_xy: tuple
    surface: float
    bed_area: float                      # cross-section at half the first layer
    bed_width: float                     # narrowest width of the contact outline
    com_height: float                    # centre of mass above the bed
    com_margin: float                    # centre of mass to the nearest contact edge (negative: outside, tips over)
    over_area: float                     # area that needs support (after ignoring spots and bridges)
    over_regions: list                   # (area, z, kind) of the regions that need support, kind overhang/island
    ignored: dict                        # spots / bridges ignored
    steep_area: float                    # beyond SOMA's design rule (warning)
    fits: bool
    cost: float = 0.0
    load_tilt: float | None = None       # load axis out of the layers, degrees (None: strength not asked for)
    load_note: str = ""
    bed_rim: float = 0.0                 # largest reach of an ignored bed rim (rounded/chamfered bottom edge), mm

    @property
    def slender(self) -> float:
        """Height of the centre of mass over its distance to the contact edge (= height / width when symmetric)."""
        return self.com_height / self.com_margin if self.com_margin > 1e-6 else math.inf


def _is_bridge(pts2d: np.ndarray, anchored: np.ndarray) -> bool:
    """A flat region is a bridge when it is at most BRIDGE_SPAN wide and held along both long sides.

    pts2d: the region's corner points, anchored: (k, 2, 2) edges where a wall runs down from the region."""
    w, across = min_width(pts2d)
    if w > BRIDGE_SPAN or w <= 0 or not len(anchored):
        return False
    along = np.array([-across[1], across[0]])
    proj = pts2d @ across
    lo, hi = proj.min(), proj.max()
    length = float(np.ptp(pts2d @ along))
    band = ANCHOR_END * (hi - lo)
    ep = anchored @ across                               # (k, 2) both ends of each anchored edge
    ln = np.linalg.norm(anchored[:, 1] - anchored[:, 0], axis=1)
    at_lo = ln[(ep <= lo + band).all(axis=1)].sum()
    at_hi = ln[(ep >= hi - band).all(axis=1)].sum()
    return at_lo >= 0.5 * length and at_hi >= 0.5 * length


def analyse(mesh: Mesh, rot: np.ndarray, down: str, bed_xy, bed_h, slope_deg: float, z0: float) -> Analysis:
    m = mesh.transformed(rot)
    v = m.verts - [0, 0, m.verts[:, 2].min()]
    tri = v[m.faces]
    cr = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area2 = np.linalg.norm(cr, axis=1)
    ok = area2 > 1e-12
    nz = np.zeros(len(tri))
    nz[ok] = cr[ok, 2] / area2[ok]
    area = area2 / 2
    zc = tri[:, :, 2].mean(axis=1)

    # contact with the bed: the first layer's cross-section (also catches cylinders lying on their side)
    bed_area, outline = cross_section(tri, cr, z0)
    hull = hull_of(outline)
    bed_width = min_width(outline)[0] if len(outline) else 0.0
    com = Mesh(v, m.faces).centre_of_mass()
    com_margin = inside_distance(hull, com[:2])

    fid = np.repeat(np.arange(len(tri)), 3)
    edges = m.edges()
    third = np.roll(m.faces, -2, axis=1).reshape(-1)      # vertex opposite edge k of each face

    # the first layer's outline as segments (cross_section returns all start points, then all end points)
    half = len(outline) // 2
    seg_a, seg_b = outline[:half], outline[half:2 * half]
    rim_z = 2 * z0 + LIFT                                # a region starting this low grows out of the first layer

    def rim_reach(pts: np.ndarray) -> float:
        """Largest distance from pts to the first layer's outline, exact up to BED_RIM_REACH (beyond: some value above
        it). Only segments near the points' box count: a segment within BED_RIM_REACH of a point lies in that box."""
        lo, hi = pts.min(axis=0) - BED_RIM_REACH - 1e-3, pts.max(axis=0) + BED_RIM_REACH + 1e-3
        near = (np.minimum(seg_a, seg_b) <= hi).all(axis=1) & (np.maximum(seg_a, seg_b) >= lo).all(axis=1)
        return float(dist_to_segments(pts, seg_a[near], seg_b[near]).max()) if near.any() else math.inf

    def overhang_regions(nz_limit: float):
        """Regions of triangles steeper than nz_limit that need support, what was ignored, and the largest reach of
        an ignored bed rim."""
        over = ok & (nz < nz_limit) & (zc > LIFT)
        idx = np.nonzero(over)[0]
        labels = components(m.faces[over], len(v))
        region_of = np.full(len(tri), -1)
        region_of[idx] = labels
        # region edges, and whether a wall runs down from them (the neighbour's third vertex lies lower)
        eo = np.nonzero(over[fid])[0]
        mate = m.mate[eo]
        has = mate >= 0
        nb_region = np.where(has, region_of[fid[np.maximum(mate, 0)]], -2)
        edge_region = region_of[fid[eo]]
        boundary = nb_region != edge_region
        edge_z = v[edges[eo], 2].min(axis=1)
        nb_z = np.where(has, v[third[np.maximum(mate, 0)], 2], np.inf)
        anchored = boundary & (nb_z < edge_z - 1e-3)
        found, ignored = [], {"spots": 0, "ledges": 0, "bridges": 0, "bed rims": 0}
        rim_max = 0.0
        for lab in np.unique(labels):
            sel = idx[labels == lab]
            a = float(area[sel].sum())
            z = float(zc[sel].mean())
            # grows out of the first layer (rounded or chamfered bottom edge): no wall below it, so the ledge rule
            # cannot measure it; measure how far it reaches past the first layer's outline instead (over the whole
            # triangles, not only their corners: a roof over a hole can have every corner above the outline).
            # Reaching further: the rules below decide, as before
            if half and tri[sel][:, :, 2].min() <= rim_z:
                pv = np.unique(m.faces[sel].reshape(-1))     # corners first: cheap, and enough when already too far
                reach = rim_reach(v[pv, :2])
                if reach <= BED_RIM_REACH:
                    reach = rim_reach(tri_samples(tri[sel][:, :, :2]))
                if reach <= BED_RIM_REACH:
                    ignored["bed rims"] += 1
                    rim_max = max(rim_max, reach)
                    continue
            anch = eo[(edge_region == lab) & anchored]
            if len(anch) == 0:                           # nothing below it: an island in the air
                if a >= ISLAND_AREA:
                    found.append((a, z, "island"))
                else:
                    ignored["spots"] += 1
                continue
            if a < SPOT_AREA:
                ignored["spots"] += 1
                continue
            held = v[edges[anch]][:, :, :2]
            held_len = float(np.linalg.norm(held[:, 1] - held[:, 0], axis=1).sum())
            if held_len > 0 and float((area[sel] * -nz[sel]).sum()) / held_len <= LEDGE_DEPTH:
                ignored["ledges"] += 1                   # sticks out less than a millimetre: prints fine
                continue
            if np.all(nz[sel] < BRIDGE_NZ) and _is_bridge(tri[sel][:, :, :2].reshape(-1, 2), held):
                ignored["bridges"] += 1
                continue
            found.append((a, z, "overhang"))
        return found, ignored, rim_max

    # support-needing overhang: slope from horizontal below Bambu's threshold angle
    regions, ignored, bed_rim = overhang_regions(-math.cos(math.radians(slope_deg)))
    over_area = sum(r[0] for r in regions)
    # SOMA's design rule (from vertical), same filter, for the warning only
    steep, _, _ = overhang_regions(-math.sin(math.radians(DESIGN_OVERHANG)))
    size = v.max(axis=0) - v.min(axis=0)
    fits = bool(size[2] <= bed_h and (
        (size[0] <= bed_xy[0] and size[1] <= bed_xy[1]) or (size[1] <= bed_xy[0] and size[0] <= bed_xy[1])))
    return Analysis(rot, down, float(size[2]), (float(size[0]), float(size[1])), float(area.sum()), bed_area,
                    bed_width, float(com[2]), com_margin, over_area, regions, ignored,
                    float(sum(r[0] for r in steep)), fits, bed_rim=bed_rim)


def needs_support(a: Analysis) -> bool:
    return any(r[0] >= SUPPORT_REGION or r[2] == "island" for r in a.over_regions) or a.over_area >= SUPPORT_TOTAL


def candidate_directions(mesh: Mesh) -> list[tuple[str, np.ndarray]]:
    """The six axes plus the normals of the three largest flat regions, as 'down' directions."""
    out = [(f"{k} down", np.array(d, float)) for k, d in AXES.items()]
    tri = mesh.verts[mesh.faces]
    cr = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    a = np.linalg.norm(cr, axis=1)
    ok = a > 1e-12
    n = cr[ok] / a[ok, None]
    key = np.round(n * 57.3).astype(int)          # about 1 degree bins
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    sums = np.bincount(inv, weights=a[ok])
    for k in np.argsort(sums)[::-1][:3]:
        d = (n[inv == k] * a[ok][inv == k, None]).sum(axis=0)
        d /= np.linalg.norm(d)
        if all(np.degrees(np.arccos(np.clip(d @ c, -1, 1))) > 1.0 for _, c in out):
            # rounded first, + 0.0: a tiny negative value showed as "-0.00" (2026-11-22)
            x, y, z = (round(float(c), 2) + 0.0 for c in d)
            out.append((f"face ({x:+.2f}, {y:+.2f}, {z:+.2f}) down", d))
    return out


def load_axis(mesh: Mesh, hint: dict) -> tuple[np.ndarray, str] | None:
    """Direction of the main stress of a loaded part (model coordinates), or None when strength does not matter.

    From "load_axis" in bambu.json (x, y, z or [dx, dy, dz]); otherwise, for a part with a "function", the model axis
    along which it is longest (a snap hook's arm, a spring's leaf). SOMA parts are modelled along the axes, so this is
    predictable; a principal-axis fit would tilt towards the diagonal of L-shaped parts such as a hook on its base."""
    spec = hint.get("load_axis")
    if spec is None and not hint.get("function"):
        return None
    if spec is not None:
        if isinstance(spec, str):
            key = spec.lower().strip().lstrip("+-")
            if key not in ("x", "y", "z"):
                raise ToolError(f'unknown "load_axis": {spec!r} (use x, y, z or [dx, dy, dz])')
            v = np.array(AXES["+" + key], float)
        else:
            try:
                v = np.asarray(spec, dtype=float).reshape(3)
            except (TypeError, ValueError):
                raise ToolError(f'"load_axis" must be x, y, z or three numbers [dx, dy, dz], not {spec!r}') from None
            big = float(np.max(np.abs(v))) if np.all(np.isfinite(v)) else math.nan
            if not math.isfinite(big) or big < 1e-12:
                raise ToolError(f'"load_axis" {spec!r} must be three finite numbers, not all zero')
            v = v / big                                   # scale first: no overflow in the norm
            v = v / np.linalg.norm(v)
        return v, tr("ld.along", spec=spec)
    ext = np.ptp(mesh.verts, axis=0)
    i = int(np.argmax(ext))
    return np.eye(3)[i], tr("ld.longest", axis="xyz"[i], mm=f"{ext[i]:.0f}")


def _tilt(rot: np.ndarray, axis: np.ndarray) -> float:
    """Angle between the load axis and the layers (0 = in the layers: strong, 90 = across them: weak)."""
    return math.degrees(math.asin(min(1.0, abs(float((rot @ axis)[2])))))


def is_stable(a: Analysis, hint: dict) -> bool:
    """Enough bed contact, and the centre of mass inside it, or only a little past it (at most a quarter of the
    contact width, as in the brim rules) when that orientation gets support to carry it."""
    if a.bed_area < BRIM_CONTACT[1]:
        return False
    if a.com_margin >= 0:
        return True
    sup_set = str((hint.get("settings") or {}).get("enable_support", "")).strip()
    sup = bool(hint["support"]) if "support" in hint else sup_set == "1" if sup_set in ("0", "1") \
        else needs_support(a)
    return sup and a.com_margin >= -a.bed_width / 4


def choose_orientation(mesh: Mesh, hint: dict, bed_xy, bed_h, slope: float, z0: float) -> Analysis:
    load = load_axis(mesh, hint)
    if "up" in hint:
        key = str(hint["up"]).lower().strip()
        key = key if key[:1] in "+-" else "+" + key
        if key not in AXES:
            raise ToolError(f'unknown "up": {hint["up"]!r} (use +x, -x, +y, -y, +z, -z)')
        down = -np.array(AXES[key], float)
        an = analyse(mesh, rotation_to_down(down), f"{key} up (bambu.json)", bed_xy, bed_h, slope, z0)
        if load:
            an.load_tilt, an.load_note = _tilt(an.rot, load[0]), load[1]
        return an
    largest = float(np.ptp(mesh.verts, axis=0).max())
    cands = []
    for name, d in candidate_directions(mesh):
        an = analyse(mesh, rotation_to_down(d), name, bed_xy, bed_h, slope, z0)
        an.cost = (an.over_area - W_BED * an.bed_area) / an.surface + W_HEIGHT * an.height / largest
        if load:
            an.load_tilt, an.load_note = _tilt(an.rot, load[0]), load[1]
        cands.append(an)
    fitting = [c for c in cands if c.fits] or cands
    # stability before cost: an orientation on a point or with the centre of mass far past its contact falls over,
    # however little support it needs (a fine process with a low support angle made that win). Same limits as the
    # brim rules; only when a stable orientation exists (tiny parts may have none).
    stable = [c for c in fitting if is_stable(c, hint)]
    fitting = stable or fitting
    if load:                       # strength next: the load must run along the layers, then the usual cost
        strong = [c for c in fitting if c.load_tilt <= STRENGTH_TILT]
        fitting = strong or [min(fitting, key=lambda c: c.load_tilt)]
    best = min(fitting, key=lambda c: c.cost)
    modelled = next(c for c in cands if c.down == "-z down")
    if any(c is modelled for c in fitting) and modelled.cost <= best.cost + KEEP_MODELLED:
        modelled.down = "as modelled"
        return modelled
    return best


# --- SOMA model -----------------------------------------------------------------------------------------------------
@dataclass
class Part:
    name: str
    step_name: str
    group: str
    color: tuple
    mesh: Mesh | None = None
    hint: dict = field(default_factory=dict)
    an: Analysis | None = None
    settings: dict = field(default_factory=dict)
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    extras: list = field(default_factory=list)       # merged parts: (Part, filament)
    brim: float = 0.0
    filament: int = 1
    own_colour: bool = False                         # its colour was chosen by hand ("colour" in bambu.json, C)
    copy_of: str = ""                              # a duplicate: the name of the part it copies
    too_big: str = ""                                # set by decide(): why it does not fit the printer (stops the build)
    foot: object = None                              # footprint(): (rotation it was made for, outline), copies share it
    opening: object = None                           # openings(): (rotation, rectangles), copies share it


def _copy_part(p: Part, name: str) -> Part:
    """A copy of a part for the duplicates: the same mesh, orientation, settings and merged parts, with its own name
    and its own list of the part's warnings (the packer adds one to the copy that has no spot)."""
    return replace(p, name=name, copy_of=p.name, warnings=list(p.warnings), extras=list(p.extras))


def linear_to_srgb(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def color_name(rgb) -> str:
    return min(COLOR_NAMES, key=lambda k: sum((a - b) ** 2 for a, b in zip(rgb, COLOR_NAMES[k])))


# --- colours: which filament prints which part (2026-11-22) --------------------------------------------------------
MAX_FILAMENTS = 32        # filament numbers a part may ask for in bambu.json (Bambu Studio: up to 32 with AMS units)


def hex_srgb(h: str) -> tuple | None:
    """'#RRGGBB' or '#RRGGBBAA' as sRGB 0..1; None when it is not a colour or fully transparent ('#00000000')."""
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})([0-9a-fA-F]{2})?", str(h or "").strip())
    if not m or (m.group(2) and int(m.group(2), 16) == 0):
        return None
    return tuple(int(m.group(1)[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _lab(rgb) -> tuple:
    """sRGB 0..1 as CIELAB (D65): L lightness 0..100, a green-red, b blue-yellow; distances there follow the eye."""
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    x = (0.4124 * lin[0] + 0.3576 * lin[1] + 0.1805 * lin[2]) / 0.95047
    y = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    z = (0.0193 * lin[0] + 0.1192 * lin[1] + 0.9505 * lin[2]) / 1.08883
    f = [v ** (1 / 3) if v > 0.008856 else 7.787 * v + 16 / 116 for v in (x, y, z)]
    return 116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])


NEUTRAL_CHROMA = 12.0     # below this (CIELAB) a colour counts as grey, black or white


def nearest_filament(rgb, colours: list, neutral_rule: bool = True) -> int:
    """The filament (1-based) whose colour looks closest to `rgb` (CIELAB distance); the lowest number on a tie, 1
    without colours. A grey, black or white part only takes a grey, black or white filament when there is one
    (2026-11-22: a mid-grey part went to a pink filament, closer in numbers but not what anyone expects).
    neutral_rule=False for filaments made from the parts' own colours (expand_filaments): they are the colours
    chosen for the parts, and the rule would overrule that choice (2026-11-23: with colour mixing, two dark greys
    shared a slightly olive mix, and the rule sent one of them to the white filament)."""
    part = _lab(rgb)
    fils = [(i, _lab(c)) for i, c in ((i, hex_srgb(h)) for i, h in enumerate(colours, 1)) if c is not None]
    if not fils:
        return 1
    neutral = lambda lab: math.hypot(lab[1], lab[2]) < NEUTRAL_CHROMA   # noqa: E731
    if neutral_rule and neutral(part) and any(neutral(lab) for _, lab in fils):
        fils = [(i, lab) for i, lab in fils if neutral(lab)]
    return min(fils, key=lambda f: (math.dist(part, f[1]), f[0]))[0]


FAR_COLOUR = 55.0         # CIELAB distance above which no filament counts as close to a part's colour (2026-11-22:
                          # blue, red and orange went to pink at ~80; grey to white 42, dark green to green 51 are fine)


def same_colour(a, b) -> bool:
    """Do two colours count as one (one filament prints both)? Close (SAME_COLOUR) or with the same name."""
    return math.dist(_lab(a), _lab(b)) < SAME_COLOUR or color_name(a) == color_name(b)


def colour_far(rgb, colours: list, n: int, strict: bool = False) -> bool:
    """Is filament n (1-based) clearly another colour than `rgb`? Then the part is not printed in its own colour.
    strict (the model's colours on the filaments): any other colour counts, since the filaments were meant to have
    the parts' own colours (2026-11-23: with 7 colours on 5 filaments, red went to orange, distance 40, unnoticed)."""
    c = hex_srgb(colours[n - 1]) if 0 < n <= len(colours) else None
    if c is None:
        return False
    return not same_colour(rgb, c) if strict else math.dist(_lab(rgb), _lab(c)) > FAR_COLOUR


def srgb_hex(rgb) -> str:
    """sRGB 0..1 as '#RRGGBB', as Bambu Studio keeps a filament's colour."""
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02X}" for c in rgb[:3])


# the colours a part can be given by hand (C in the form's parts list, "colour" in bambu.json): the named ones, so
# that the form, the report and Bambu Studio all call it the same (2026-11-23)
PALETTE = list(COLOR_NAMES)


def parse_colour(v) -> tuple | None:
    """A part's own colour from bambu.json / --colour: '#RRGGBB' or a colour name (English: red, dark grey, ...);
    None for "auto" or nothing. Anything else is an error, so a typo does not silently print in the model's colour."""
    if v in (None, "", "auto"):
        return None
    s = str(v).strip().lower()
    if s in COLOR_NAMES:
        return COLOR_NAMES[s]
    rgb = hex_srgb(s)
    if rgb is None:
        raise ToolError(f"unknown colour {v!r}: use #RRGGBB or one of {', '.join(PALETTE)}")
    return rgb


SAME_COLOUR = 12.0        # CIELAB distance below which two part colours share one filament (just visibly different)


def model_colours(rgbs: list, slots: int) -> list:
    """The filament colours for parts of these colours with `slots` filaments: one per distinct colour, in the order
    the parts come; with more colours than slots the two closest groups share one filament (the colour of the group
    with the most parts), until they fit. 2026-11-23: Bambu Studio cannot add filaments to a project (its command line
    crashes with a second one), so a colour template's own filaments are given the model's colours instead."""
    groups: list[list] = []                               # [rgb of the group, number of parts]
    for rgb in rgbs:
        # the same colour name shares one too (2026-11-23: two dark greys of the model, #736B59 and #4C4C47, took two
        # filaments that the form and the report both called "dark grey")
        g = next((g for g in groups if same_colour(rgb, g[0])), None)
        if g:
            g[1] += 1
        else:
            groups.append([tuple(rgb), 1])
    while len(groups) > max(1, slots):
        i, j = min(((i, j) for i in range(len(groups)) for j in range(i + 1, len(groups))),
                   key=lambda ij: (math.dist(_lab(groups[ij[0]][0]), _lab(groups[ij[1]][0])), ij))
        keep, drop = (i, j) if groups[i][1] >= groups[j][1] else (j, i)
        groups[keep][1] += groups[drop][1]
        del groups[drop]
    return [g[0] for g in groups]


UNAVAILABLE = 20.0        # CIELAB distance from the nearest colour Bambu Lab sells above which the form and the report
                          # say the colour is not available in that filament (2026-11-23)


def colour_distance(a, b) -> float:
    """How different two colours (sRGB 0..1) look: CIELAB distance."""
    return math.dist(_lab(a), _lab(b))


def snap_colours(rgbs: list, official: list) -> list[tuple]:
    """Per colour (sRGB 0..1) the nearest colour Bambu Lab sells the filament in: (hex, {language: name} or {}, far).
    far: farther than UNAVAILABLE, the part prints in another colour than it has. Without a list the colour as it is."""
    out = []
    for rgb in rgbs:
        if not official:
            out.append((srgb_hex(rgb), {}, False))
            continue
        h, names = min(official, key=lambda o: math.dist(_lab(rgb), _lab(hex_srgb(o[0]))))
        out.append((h, names, math.dist(_lab(rgb), _lab(hex_srgb(h))) > UNAVAILABLE))
    return out


def slot_colours(rgbs: list, official: list) -> tuple[list[str], list[dict]]:
    """The filaments a project gets for parts of these colours (sRGB 0..1, in model order): ('#RRGGBB' per filament,
    {language: name} per filament). One per distinct colour (model_colours, at most MAX_FILAMENTS), each moved to the
    nearest colour Bambu Lab sells (snap_colours); two that land on one sold colour share one filament."""
    hexes, names = [], []
    for h, n, _ in snap_colours(model_colours(rgbs, MAX_FILAMENTS), official):
        if h not in hexes:
            hexes.append(h)
            names.append(n)
    return hexes or ["#FFFFFF"], names or [{}]


MAX_MIXES = 16           # mixed filaments per project at most (Bambu Studio has a limit; its value is not documented)


def mix_plan(rgbs: list, recipes: list) -> tuple[list[str], list, list[dict]]:
    """The filaments for parts of these colours (sRGB 0..1) with colour mixing (2026-11-23): per distinct colour the
    nearest of the mode's base colours and Bambu's measured mixes of them. Returns (the base filaments to load,
    '#RRGGBB'; the mixed ones as (1-based base numbers, shares, '#RRGGBB'); a name per filament {'en': ...}). Only
    the bases that are used, in the recipes' order; two colours that land on one mix share it."""
    bases: list = []
    for comps, _, _ in recipes:
        for c in comps:
            if c not in bases:
                bases.append(c)
    cands = [((b,), None, b[1]) for b in bases] + [(tuple(c), tuple(r), h) for c, r, h in recipes]
    chosen: list = []
    for rgb in model_colours(rgbs, MAX_MIXES + len(bases)):
        best = min(cands, key=lambda c: colour_distance(rgb, hex_srgb(c[2])))
        if best not in chosen:
            chosen.append(best)
    if sum(1 for c in chosen if c[1]) > MAX_MIXES:       # too many mixes: the closest pairs share one
        chosen = chosen[:len(bases) + MAX_MIXES]
    used = [b for b in bases if any(b in c[0] for c in chosen)]
    phys = [h for _, h in used]
    names = [{"en": k} for k, _ in used]
    mixes = []
    for comps, ratios, h in chosen:
        if ratios:
            mixes.append(([used.index(b) + 1 for b in comps], list(ratios), h))
            names.append({"en": " + ".join(f"{round(r * 100)}% {k}" for (k, _), r in zip(comps, ratios))})
    return phys or ["#FFFFFF"], mixes, names


def _hsv_dist(src, dst) -> float:
    h1, s1, v1 = colorsys.rgb_to_hsv(*src)
    h2, s2, v2 = colorsys.rgb_to_hsv(*dst)
    a1, a2 = math.radians(h1 * 360), math.radians(h2 * 360)
    dx = math.cos(a1) * s1 * v1 - math.cos(a2) * s2 * v2
    dy = math.sin(a1) * s1 * v1 - math.sin(a2) * s2 * v2
    return min(1.2, math.hypot(dx, dy))


MAX_FLUSH = 900           # mm³, Bambu Studio's g_max_flush_volume
FLUSH_MARGIN = 1.4        # Orientr's estimate is this much above Bambu Studio's colour formula (see flush_volume;
                          # 1.3 left black->white 5 % below the window's own value, 2026-11-23)


def flush_volume(src, dst, base: float) -> int:
    """mm³ to purge when a nozzle goes from colour `src` to `dst` (sRGB 0..1): Bambu Studio's colour formula times
    FLUSH_MARGIN, plus `base` (the nozzle's minimum, read from the template), at most MAX_FLUSH. Bambu Studio itself
    adds measured data per filament pair on top; without it this errs on the generous side (2026-11-23: compared with
    a 5-colour H2D project made in the window: no pair lower here, black->white 900 / 900, pink->white 334 / 415)."""
    return int(min(MAX_FLUSH, _flush_formula(src, dst) * FLUSH_MARGIN + base))


def _flush_formula(src, dst) -> float:
    """Bambu Studio's colour-based purge estimate without its minimum (FlushVolCalculator::calc_flush_vol_rgb in
    src/libslic3r/FlushVolCalc.cpp, master on 2026-11-23)."""
    lum = lambda c: c[0] * 0.3 + c[1] * 0.59 + c[2] * 0.11   # noqa: E731
    hs = _hsv_dist(src, dst)
    lf, lt = lum(src), lum(dst)
    if lt >= lf:
        lumi = (lt - lf) ** 0.7 * 560
    else:
        lumi = (lf - lt) * 80
        hs = min(0.67 * colorsys.rgb_to_hsv(*dst)[2] + 0.33 * colorsys.rgb_to_hsv(*src)[2], hs)
    hf = 230 * hs
    return max(math.sqrt(max(0.0, hf * hf + lumi * lumi - 2 * hf * lumi * math.cos(math.radians(120)))), 60.0)


def flush_base(colours: list, matrix: list, nozzles: int) -> list:
    """Per nozzle the minimum purge the template's own flush matrix shows on top of the colour formula (the median
    over pairs of clearly different colours; 130 mm³ when there are none, as on the H2D), between 0 and 300."""
    n = len(colours)
    rgb = [hex_srgb(c) or (1.0, 1.0, 1.0) for c in colours]   # Bambu Studio: transparent counts as white
    out = []
    for z in range(nozzles):
        d = []
        for i in range(n):
            for j in range(n):
                k = z * n * n + i * n + j
                if i != j and k < len(matrix) and math.dist(_lab(rgb[i]), _lab(rgb[j])) > SAME_COLOUR:
                    try:
                        raw = float(matrix[k])
                    except (TypeError, ValueError):
                        continue
                    if raw < MAX_FLUSH:                       # a clamped value says nothing about the minimum
                        d.append(raw - _flush_formula(rgb[i], rgb[j]))
        d.sort()
        out.append(max(0.0, min(300.0, d[len(d) // 2])) if d else 130.0)
    return out


def colour_choices(t) -> list:
    """The filament colours a part may be matched to by colour: with the model's colours on the filaments only the
    ones recolour() gave a colour (2026-11-23: with 3 colours on 5 filaments, a part could land on filament 4 or 5,
    which kept the template's old colour), else all of the template's."""
    colours = list(getattr(t, "colours", []) or [])
    used = getattr(t, "model_used", 0)
    return colours[:used] if getattr(t, "colour_mode", "") == "model" and used else colours


def colour_parts(entries, skipped=()) -> list:
    """Of (name, hint) in model order, the names whose colour counts for the model's colours on the filaments: no
    filament of their own; a merged part only with "filament": "auto" and a host that is printed (`skipped`: parts
    not printed besides those whose hint says so). The form and make_project both use it, so the form shows the
    filaments the project gets."""
    entries = list(entries)
    skipped = set(skipped) | {n for n, h in entries if h.get("skip")}
    return [n for n, h in entries if not h.get("skip") and h.get("filament") in (None, "", "auto")
            and (not h.get("merge_into") or (h.get("filament") == "auto" and h["merge_into"] not in skipped))]


def by_colour(entries) -> list:
    """(name, hint) with every part going by its colour ("filament": "auto"), merged ones too: for filaments made
    per colour, where a filament number means nothing (make_project and the form alike)."""
    return [(n, {**h, "filament": "auto"}) for n, h in entries]


def filament_label(t, n: int) -> str:
    """'3 Bambu PLA Basic, white' for the report and the form: number, preset and colour of filament n of `t`."""
    names, colours = list(getattr(t, "filament_names", []) or []), list(getattr(t, "colours", []) or [])
    name = names[n - 1] if 0 < n <= len(names) else ""
    rgb = hex_srgb(colours[n - 1]) if 0 < n <= len(colours) else None
    own = list(getattr(t, "colour_names", []) or [])      # Bambu Lab's own name of a sold colour (expand_filaments)
    sold = official_name(own[n - 1]) if 0 < n <= len(own) else ""
    return f"{n} {name}".strip() + (f", {sold}" if sold else f", {tr('col.' + color_name(rgb))}" if rgb else "")


def official_name(names: dict) -> str:
    """Bambu Lab's name of a colour in the tool's language, else English; '' without names."""
    from orientr_i18n import language
    return str((names or {}).get(language()) or (names or {}).get("en") or "")


def assign_filament(p: Part, t) -> None:
    """The filament a part prints with: its own choice ("filament" in bambu.json, or F in the form's parts list),
    else, when the template has more than one filament, the one whose colour is closest to the part's colour in the
    model; with one filament always 1. The choice goes into the part's reasons."""
    have = max(1, int(getattr(t, "filaments", 1) or 1))
    # filaments made per colour (expand_filaments): every part goes by its colour, a number means nothing there
    want = None if getattr(t, "generated", False) else p.hint.get("filament")
    if want not in (None, "", "auto"):
        n = int(want)
        if n > have:
            p.warnings.append(tr("w.filament", n=n, have=have))
            n = 1
        p.filament = n
        if have > 1:
            p.reasons.append(tr("r.fil_chosen", fil=filament_label(t, n)))
        return
    if have == 1:
        p.filament = 1
        return
    p.filament = nearest_filament(p.color, colour_choices(t), not getattr(t, "generated", False))
    colour = tr("col." + color_name(p.color))
    p.reasons.append(tr("r.fil_own_colour" if p.own_colour else "r.fil_colour", fil=filament_label(t, p.filament),
                        colour=colour))
    if getattr(t, "generated", False):                    # one filament per colour, made for this project: only a
        c = hex_srgb((list(t.colours) + [""])[p.filament - 1])   # colour Bambu Lab does not sell differs (2026-11-23)
        if c and math.dist(_lab(p.color), _lab(c)) > UNAVAILABLE:
            p.warnings.append(tr("w.colour_unmixable" if getattr(t, "mixing", False) else "w.colour_unavailable",
                                 colour=colour, fil=filament_label(t, p.filament)))
        return
    model = getattr(t, "colour_mode", "") == "model"
    if colour_far(p.color, getattr(t, "colours", []), p.filament, strict=model):   # never silently in another colour
        # with the model's colours only when the model has more colours than the template has filaments
        p.warnings.append(tr("w.fil_merged" if model else "w.fil_far", colour=colour,
                             fil=filament_label(t, p.filament), have=have))


def printable_parts(ws: Path) -> list[tuple[str, str, str, tuple]]:
    """(name, step_name, group, sRGB colour) of every printable part of the last build, without exporting."""
    mj = ws / ".soma" / "model.map.json"
    if not mj.exists():
        raise ToolError(tr("e.no_build"))
    # SOMA's own files (not a documented interface: a SOMA update may change them; --selftest checks them). The colours
    # are only a nicety: when model.glb is not as expected the parts are grey. The parts list is needed: when it is
    # not as expected, a clear message instead of a Python error (2026-11-22)
    colors = {}
    glb = ws / ".soma" / "model.glb"
    try:
        if glb.exists():
            b = glb.read_bytes()
            ln = struct.unpack_from("<I", b, 12)[0]
            j = json.loads(b[20:20 + ln])
            for mat in j.get("materials", []):
                f = mat.get("pbrMetallicRoughness", {}).get("baseColorFactor")
                if f and ":" in mat.get("name", ""):
                    colors[mat["name"].split(":", 1)[1]] = tuple(linear_to_srgb(c) for c in f[:3])
    except (struct.error, ValueError, KeyError, TypeError, AttributeError, IndexError):
        colors = {}
    try:
        return [(p["name"], p["step_name"], p.get("group") or "", colors.get(p["step_name"], (0.6, 0.6, 0.6)))
                for p in json.loads(mj.read_text(encoding="utf-8"))["parts"] if p.get("role", "part") == "part"]
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ToolError(tr("e.soma_changed", what=".soma/model.map.json")) from None


def build_state(ws: Path) -> dict:
    """{"ok": last build succeeded, "stale": code changed after it, "message": for the user}."""
    bj, mj = ws / ".soma" / "build.json", ws / ".soma" / "model.map.json"
    if not bj.exists() or not mj.exists():
        return {"ok": False, "stale": False, "message": tr("e.no_build")}
    try:
        build = json.loads(bj.read_text(encoding="utf-8"))
    except ValueError:
        return {"ok": False, "stale": False, "message": "the build status cannot be read: run `soma build`"}
    if build.get("status") != "ok":
        return {"ok": False, "stale": False, "message": "the last `soma build` failed: fix and build first"}
    newest = max((p.stat().st_mtime for p in [ws / "model.py", *ws.glob("parts/*.py"), ws / "parameters.json"]
                  if p.exists()), default=0)
    stale = newest > build.get("finished", 0) + 1
    return {"ok": True, "stale": stale, "message": "model.py or parts/ changed after the last build; the parts come "
                                                   "from the last good build" if stale else "build ok"}


def stl_from_step(ws: Path, parts: list[Part], tmp: Path) -> bool:
    """Writes `<step_name>.stl` of every part into tmp from output/model.step of the last good build, meshed with the
    same function and tolerance as `soma export` (tested 2026-11-18: volumes within 0.001 %, bounding boxes within
    0.001 mm; a few seconds instead of rebuilding the model). False when that STEP cannot be used."""
    step, bj = ws / "output" / "model.step", ws / ".soma" / "build.json"
    try:
        build = json.loads(bj.read_text(encoding="utf-8"))
        written = step.stat().st_mtime
    except (OSError, ValueError):
        return False
    if not build.get("started", 0) - 1 <= written <= build.get("finished", 0) + 1:
        return False                                      # written by another build (or by hand): do not trust it
    written: list[Path] = []
    try:
        import cadquery as cq
        from soma import meshexport
        shapes: dict = {}

        def walk(a, loc):
            loc = loc * a.loc
            if a.obj is not None:
                shapes.setdefault(a.name, a.obj.moved(loc))
            for c in a.children:
                walk(c, loc)

        walk(cq.Assembly.importStep(str(step)), cq.Location())
        if any(p.step_name not in shapes for p in parts):
            return False
        tmp.mkdir(parents=True, exist_ok=True)
        for p in parts:
            f = tmp / f"{p.step_name}.stl"
            written.append(f)
            meshexport.export_mesh(shapes[p.step_name], "stl", f, p.name)
    except Exception as e:                                # any problem: fall back to `soma export`
        print(f"note: parts not read from output/model.step ({type(e).__name__}: {e}); exporting them instead")
        for f in written:                                 # no leftovers that could stand in for a missing export
            f.unlink(missing_ok=True)
        return False
    return True


def preload_libraries() -> None:
    """Load the libraries that reading the model and choosing the orientation need (CadQuery, SOMA's mesh export,
    scipy) in a background thread while the form is open (2026-11-22, measured: about 2-3 s at every
    Analyze or Generate, up to about 40 s after a long pause, when Windows reads them from disk again). Only imports:
    nothing is read or kept, so the result cannot be out of date. An import started by Analyze meanwhile waits for
    this one (Python's import lock) instead of loading twice; any error here shows up there as before."""
    def work() -> None:
        try:
            import cadquery  # noqa: F401
            from soma import meshexport  # noqa: F401
            from scipy.spatial import ConvexHull  # noqa: F401
            from scipy.sparse.csgraph import connected_components  # noqa: F401
        except BaseException:                             # never break the form over this
            pass
    import threading
    threading.Thread(target=work, name="preload", daemon=True).start()


def load_model(ws: Path, hints: dict, tmp: Path) -> list[Part]:
    state = build_state(ws)
    if not state["ok"]:
        raise ToolError(state["message"])
    if state["stale"]:
        print(f"warning: {state['message']}")
    parts = [Part(name, step, group, rgb, hint=dict(hints.get(name, {})))
             for name, step, group, rgb in printable_parts(ws)]
    for p in parts:                                       # a colour chosen by hand wins over the model's (2026-11-23)
        own = parse_colour(p.hint.get("colour"))
        if own:
            p.color, p.own_colour = own, True
    unknown = set(hints) - {p.name for p in parts}
    if unknown:
        print(f"warning: bambu.json names parts that are not printable parts: {', '.join(sorted(unknown))}")
    parts = [p for p in parts if not p.hint.get("skip")]
    if not parts:
        raise ToolError(tr("e.no_printable"))
    if not stl_from_step(ws, parts, tmp):
        # `soma export` runs model.py again (as long as a build): only when the STEP of the last build cannot be used
        cmd = [sys.executable, "-m", "soma", "export", "--all", "--format", "stl", "--out", str(tmp)]
        r = subprocess.run(cmd, cwd=ws, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise ToolError(tr("e.export_failed", out=f"{r.stdout}{r.stderr}"))
    for p in parts:
        f = tmp / f"{p.step_name}.stl"
        if not f.exists():
            raise ToolError(tr("e.export_missing", name=p.name, file=f.name))
        p.mesh = Mesh.from_triangles(read_stl(f), p.name)
    return parts


def _number(v) -> float:
    try:
        return float(str(v).strip().rstrip("%"))
    except ValueError:
        return 0.0


# --- rules ----------------------------------------------------------------------------------------------------------
RIM_ANGLES = (25, 20, 15, 10)   # support thresholds tried for a part whose rounded bottom edge Bambu Studio would flag


def rim_free_angle(p: Part, t: Template) -> int | None:
    """The highest support threshold angle (below the profile's) at which the part's ignored bottom edge no longer
    counts as overhang, while its real overhang keeps (nearly) all its support; None if there is none.

    Bambu Studio flags a rounded bottom edge just above the bed as an overhang it "could not get support" for
    (2026-11-18; lowering the threshold in the Support tab cleared it). The tool already ignores such an edge,
    so a lower threshold for this part only tells Bambu Studio the same, as long as no real overhang is lost."""
    a = p.an
    bed_xy = (t.bed_x[1] - t.bed_x[0] - 2 * MARGIN, t.bed_y[1] - t.bed_y[0] - 2 * MARGIN)
    for angle in RIM_ANGLES:
        if angle >= t.slope:
            continue
        an = analyse(p.mesh, a.rot, a.down, bed_xy, t.bed_h, angle, t.first_layer / 2 + 1e-6)
        if an.ignored.get("bed rims"):
            continue                                      # the edge still counts at this angle: try lower
        # the real overhang may lose at most a spot's worth (the rules ignore spots < SPOT_AREA anyway) or 10 %:
        # e.g. a test part's cap at 20° keeps 21.5 of 24.4 mm2, only the edges of a flat ceiling between 20° and 25°
        if an.over_regions and a.over_area - an.over_area <= max(SPOT_AREA, 0.1 * a.over_area):
            return angle
        return None                                       # lower angles lose even more real overhang
    return None


def decide(p: Part, t: Template) -> None:
    a = p.an
    h = p.hint
    # support
    if "support" in h:
        sup = bool(h["support"])
        p.reasons.append(tr("r.sup_on_json" if sup else "r.sup_off_json"))
    elif t.support_mode in ("on", "off"):
        sup = t.support_mode == "on"
        p.reasons.append(tr("r.sup_on_all" if sup else "r.sup_off_all"))
        if not sup and needs_support(a):
            p.warnings.append(tr("w.sup_off", area=f"{a.over_area:.0f}"))
    else:
        sup = needs_support(a)
        if sup:
            big = max(r[0] for r in a.over_regions)
            isl = sum(1 for r in a.over_regions if r[2] == "island")
            p.reasons.append(tr("r.sup_on", n=len(a.over_regions), area=f"{a.over_area:.0f}", big=f"{big:.0f}",
                                slope=f"{t.slope:.0f}")
                             + (tr("r.islands", n=isl) if isl else "")
                             + (tr("r.rim", mm=f"{a.bed_rim:.1f}") if a.ignored.get("bed rims") else ""))
        else:
            why = tr("r.overhang", area=f"{a.over_area:.0f}") if a.over_area else tr("r.no_overhang")
            ign = [tr(f"i.{k}", n=v) for k, v in a.ignored.items() if v]
            p.reasons.append(tr("r.sup_off", why=why) + (tr("r.ignored", list=", ".join(ign)) if ign else ""))
    p.settings["enable_support"] = "1" if sup else "0"
    if sup:
        p.settings["support_type"] = "tree(auto)"
        if a.ignored.get("bed rims") and "support_threshold_angle" not in (h.get("settings") or {}):
            angle = rim_free_angle(p, t)
            if angle:                                     # Bambu Studio then leaves the bottom edge alone too
                p.settings["support_threshold_angle"] = str(angle)
                p.reasons.append(tr("r.rim_angle", deg=angle, base=f"{t.slope:.0f}"))
    # brim
    slender = a.slender
    # the centre of mass lies a little past the contact area and support is on under the overhang: the part is held
    # by the bed contact and that support, it does not tip. Only for a small overshoot (support is no reliable side
    # restraint), and the lever shrinks with it: height / (half the contact width - overshoot). Further out: tips.
    sup_set = str(h.get("settings", {}).get("enable_support", "")).strip()
    sup_eff = sup_set == "1" if sup_set in ("0", "1") else sup     # a per-part setting overrides it later on
    over = -a.com_margin
    rests = sup_eff and 0 < over <= a.bed_width / 4
    if rests:
        slender = a.com_height / (a.bed_width / 2 - over)
        p.reasons.append(tr("r.rests", mm=f"{over:.1f}"))
    if "brim" in h:
        p.brim = float(h["brim"] or 0)
        p.reasons.append(tr("r.brim_json", mm=f"{p.brim:g}") if p.brim else tr("r.no_brim_json"))
    elif t.brim_mode == "off":
        p.brim = 0.0
        p.reasons.append(tr("r.no_brim_all"))
        if slender > BRIM_SLENDER[0] or a.bed_area < BRIM_CONTACT[0]:
            p.warnings.append(tr("w.brim_off"))
    else:
        level, why = 0, []
        for i, lim in enumerate(BRIM_SLENDER):
            if slender > lim:
                level = i + 1
        if slender > BRIM_SLENDER[0]:
            lever = (tr("b.lever_rest", w=f"{a.bed_width:.1f}", o=f"{over:.1f}") if rests
                     else tr("b.lever", m=f"{a.com_margin:.1f}"))
            why.append(tr("b.tall", h=f"{a.com_height:.0f}", lever=lever, r=f"{slender:.1f}")
                       if math.isfinite(slender) else tr("b.tips"))
        for i, lim in enumerate(BRIM_CONTACT):
            if a.bed_area < lim:
                level = max(level, i + 1)
        if a.bed_area < BRIM_CONTACT[0]:
            why.append(tr("b.small_contact", a=f"{a.bed_area:.0f}"))
        used = sorted({p.filament} | {f for _, f in p.extras})      # the filaments this object prints with
        warp = [t.warps[f - 1] for f in used if 0 < f <= len(t.warps) and t.warps[f - 1]]
        if level == 0 and warp and max(a.size_xy) > WARP_LENGTH:
            level = 1
            why.append(tr("b.warp_long", warp="; ".join(warp), l=f"{max(a.size_xy):.0f}"))
        if level == 0 and warp and (a.bed_area < WARP_SMALL[0] or max(a.size_xy) < WARP_SMALL[1]):
            level = 1
            why.append(tr("b.warp_small", warp="; ".join(warp), a=f"{a.bed_area:.0f}", l=f"{max(a.size_xy):.0f}"))
        if t.brim_mode == "on" and level == 0:               # menu: brim everywhere, at least the small width
            level = 1
            why.append(tr("b.all"))
        p.brim = BRIM_WIDTH[level - 1] if level else 0.0
        p.reasons.append(tr("r.brim", mm=f"{p.brim:g}", why="; ".join(why)) if level else
                         tr("r.no_brim", a=f"{a.bed_area:.0f}", r=f"{slender:.1f}"))
    if p.brim:
        p.settings["brim_type"] = "outer_only"
        p.settings["brim_width"] = f"{p.brim:g}"
    else:
        p.settings["brim_type"] = "no_brim"
    # walls and infill: the rules only ever raise the project-wide value (menu or template), never lower it
    def at_least(key: str, value: str) -> str | None:
        if _number(value) > _number(t.base(key)):
            p.settings[key] = value
            return value
        return None

    fn = h.get("function")
    if fn:
        if fn not in FUNCTION_SETTINGS:
            raise ToolError(f'{p.name}: unknown "function" {fn!r} (use {", ".join(FUNCTION_SETTINGS)})')
        raised = [f"{k} {v}" for k, v in FUNCTION_SETTINGS[fn].items() if at_least(k, v)]
        p.reasons.append(tr("r.function", fn=fn) + (": " + ", ".join(raised) if raised else ""))
    else:
        side = max(*a.size_xy, a.height)
        vol = p.mesh.volume()
        if (side < TINY_SIDE or vol < TINY_VOLUME) and at_least("wall_loops", "4"):
            p.reasons.append(tr("r.small", s=f"{side:.0f}", v=f"{vol / 1000:.1f}"))
    if "walls" in h:
        p.settings["wall_loops"] = str(int(h["walls"]))
        p.reasons.append(tr("r.walls_json", n=h["walls"]))
    if "infill" in h:
        p.settings["sparse_infill_density"] = str(h["infill"])
        p.reasons.append(tr("r.infill_json", v=h["infill"]))
        if _number(h["infill"]) >= 100:           # 100 % only slices with the rectilinear pattern
            p.settings["sparse_infill_pattern"] = FULL_INFILL_PATTERN
            p.reasons.append(tr("r.rectilinear"))
    for k, v in h.get("settings", {}).items():
        p.settings[k] = str(v)
        p.reasons.append(tr("r.setting_json", k=k, v=v))
    # strength: the load should run along the layers
    if a.load_tilt is not None:
        p.reasons.append(tr("r.strength", note=a.load_note, deg=f"{a.load_tilt:.0f}"))
        if a.load_tilt > STRENGTH_TILT:
            p.warnings.append(tr("w.load", deg=f"{a.load_tilt:.0f}",
                                 advice=tr("w.load_up" if "up" in h else "w.load_none")))
    # warnings
    ux, uy = t.bed_x[1] - t.bed_x[0] - 2 * MARGIN, t.bed_y[1] - t.bed_y[0] - 2 * MARGIN
    bx, by = (s + 2 * p.brim for s in a.size_xy)
    if not a.fits or not ((bx <= ux and by <= uy) or (by <= ux and bx <= uy)):
        p.too_big = tr("w.fit", x=f"{a.size_xy[0]:.0f}", y=f"{a.size_xy[1]:.0f}", z=f"{a.height:.0f}",
                       brim=tr("w.fit_brim", mm=f"{p.brim:g}") if p.brim else "",
                       ux=f"{ux:.0f}", uy=f"{uy:.0f}", uz=f"{t.bed_h:.0f}")
        p.warnings.append(p.too_big)                      # make_project stops with it before anything is sliced
    if a.steep_area > SPOT_AREA and not sup:
        p.warnings.append(tr("w.steep", a=f"{a.steep_area:.0f}", deg=f"{DESIGN_OVERHANG:.0f}"))
    if a.bed_area < 1.0:
        p.warnings.append(tr("w.no_contact"))
    if a.com_margin < 0 and not rests:                   # a small overshoot over support: rests on it (see brim)
        p.warnings.append(tr("w.tips_far" if sup_eff else "w.tips"))


# --- plates ---------------------------------------------------------------------------------------------------------
# Outlines (2026-11-23): parts are packed by their outline seen from above, not by their bounding box (two round tank
# halves of 160 mm fit side by side on an H2D plate only diagonally). An outline is kept as its support function: in
# each of K_DIRS fixed directions how far it reaches. That is the smallest K_DIRS-gon around the convex outline (for
# a circle at most 0.2 % larger), so it is on the safe side; a rectangle is exact. Room around it is + r on every
# value, the outline of where two parts touch (Minkowski sum) is the sum, a quarter turn or a mirror a shift of the
# values. Concave parts count by their convex outline: nothing is nested inside a ring.
K_DIRS = 48               # divisible by 4, so quarter turns and mirrors map directions onto directions
_ANG = 2 * np.pi * np.arange(K_DIRS) / K_DIRS
_U = np.stack([np.cos(_ANG), np.sin(_ANG)], axis=1)       # (K, 2) unit directions
_DET = math.sin(2 * math.pi / K_DIRS)
_EPS = 1e-6


def outline(points) -> np.ndarray:
    """Support values (K_DIRS,) of 2D points (n, 2): the outline seen from above."""
    return (np.asarray(points, dtype=float)[:, :2] @ _U.T).max(axis=0)


def outline_rect(x0: float, x1: float, y0: float, y1: float) -> np.ndarray:
    return outline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _quarter(h: np.ndarray) -> np.ndarray:
    """The outline turned 90° counter-clockwise ((x, y) -> (-y, x), as write_3mf turns a part)."""
    return np.roll(h, K_DIRS // 4)


def _mirror(h: np.ndarray, fx: bool, fy: bool) -> np.ndarray:
    k = np.arange(K_DIRS)
    if fx:
        h = h[(K_DIRS // 2 - k) % K_DIRS]
    if fy:
        h = h[(-k) % K_DIRS]
    return h


def _neg(h: np.ndarray) -> np.ndarray:
    """The outline turned half round (-P)."""
    return np.roll(h, K_DIRS // 2)


def _corners(h: np.ndarray) -> np.ndarray:
    """The corners (K, 2) of an outline: where the line of each direction meets the next one's."""
    hb = np.roll(h, -1)
    ub = np.roll(_U, -1, axis=0)
    x = (h * ub[:, 1] - hb * _U[:, 1]) / _DET
    y = (_U[:, 0] * hb - ub[:, 0] * h) / _DET
    return np.stack([x, y], axis=1)


def _crossings(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Points where the edges of two polygons (corner arrays) cross."""
    p, r = a, np.roll(a, -1, axis=0) - a
    q, s = b, np.roll(b, -1, axis=0) - b
    rxs = r[:, None, 0] * s[None, :, 1] - r[:, None, 1] * s[None, :, 0]
    qp = q[None, :, :] - p[:, None, :]
    ok = np.abs(rxs) > 1e-12
    rxs = np.where(ok, rxs, 1.0)
    tt = (qp[..., 0] * s[None, :, 1] - qp[..., 1] * s[None, :, 0]) / rxs
    uu = (qp[..., 0] * r[:, None, 1] - qp[..., 1] * r[:, None, 0]) / rxs
    hit = ok & (tt >= -_EPS) & (tt <= 1 + _EPS) & (uu >= -_EPS) & (uu <= 1 + _EPS)
    pts = p[:, None, :] + tt[..., None] * r[:, None, :]
    return pts[hit]


def _place(f: np.ndarray, z: np.ndarray, placed: list, zones: list, bounds: tuple, edge=(0.0, 0.0, 0.0, 0.0)):
    """Where the centre of a part goes (x, y), or None: as far back as it can, then as far left (the bottom-left fill
    of the bounding boxes before, 2026-11-17). f: the part's slot outline (its outline plus half the gap and half its
    brim or support room), z: its outline as the no-go zones see it; placed: [(slot outline, centre)] on this plate,
    zones: outlines of the no-go zones. A spot is free when the slot stays inside `bounds`, does not overlap a placed
    slot and z does not overlap a zone. Candidates: the corners of every spot where the part touches a placed part
    or a zone, the edges of the plate, and where two of those meet. edge: extra room to the left, right, front and back
    edge (a part with tree support at a nozzle area's edge at the tight level, see pack)."""
    bx0, bx1, by0, by1 = bounds
    lo_x, hi_x = bx0 + f[K_DIRS // 2] + edge[0], bx1 - f[0] - edge[1]   # where the centre may go so the slot stays
    lo_y, hi_y = by0 + f[3 * K_DIRS // 4] + edge[2], by1 - f[K_DIRS // 4] - edge[3]   # on the plate
    if lo_x > hi_x + _EPS or lo_y > hi_y + _EPS:
        return None
    # forbidden outlines for the centre: placed slot + (-f) moved to its centre; zone + (-z)
    nfp = [h + _neg(f) + _U @ np.asarray(c) for h, c in placed] + [zh + _neg(z) for zh in zones]
    box = np.array([[lo_x, lo_y], [hi_x, lo_y], [hi_x, hi_y], [lo_x, hi_y]])
    polys = [_corners(h) for h in nfp]
    cands = [box] + polys + [_crossings(box, q) for q in polys]
    for i in range(len(polys)):
        a = polys[i]
        for j in range(i + 1, len(polys)):
            b = polys[j]
            if (a[:, 0].min() <= b[:, 0].max() and b[:, 0].min() <= a[:, 0].max()
                    and a[:, 1].min() <= b[:, 1].max() and b[:, 1].min() <= a[:, 1].max()):
                cands.append(_crossings(a, b))
    c = np.vstack([x for x in cands if len(x)])
    c = c[(c[:, 0] >= lo_x - 1e-4) & (c[:, 0] <= hi_x + 1e-4) & (c[:, 1] >= lo_y - 1e-4) & (c[:, 1] <= hi_y + 1e-4)]
    if not len(c):
        return None
    c[:, 0] = np.clip(c[:, 0], lo_x, hi_x)
    c[:, 1] = np.clip(c[:, 1], lo_y, hi_y)
    c = c[np.lexsort((np.round(c[:, 0], 4), -np.round(c[:, 1], 4)))]     # back first, then left
    free = np.ones(len(c), dtype=bool)
    proj = c @ _U.T                                                        # (n, K)
    for h in nfp:                                                          # strictly inside = overlap
        free &= ~np.all(proj < h[None, :] - 1e-4, axis=1)
    i = int(np.argmax(free))
    return (float(c[i, 0]), float(c[i, 1])) if free[i] else None


def footprint(p: Part) -> np.ndarray:
    """The outline of a part (with the parts merged into it) seen from above in its chosen orientation, around the
    centre of its bounding box: write_3mf puts that centre on the spot pack() chose."""
    if p.foot is None or p.foot[0] is not p.an.rot:
        v = np.vstack([p.mesh.verts @ p.an.rot.T] + [e.mesh.verts @ p.an.rot.T for e, _ in p.extras])
        ctr = (v.min(axis=0) + v.max(axis=0)) / 2
        p.foot = (p.an.rot, outline(v[:, :2] - ctr[:2]))
    return p.foot[1]


# --- openings inside a part (2026-11-23, user's wish) ------------------------------------------------------------------
# A ring-shaped part (the Lid plate: a frame round a large window) has room inside its outline. An opening counts only
# when nothing of the part lies above it at any height, so a part placed there never meets it. The top view is drawn on
# a grid of HOLE_CELL mm (numpy and scipy only, as the rest of the tool: no extra package in every model's Python),
# grown by one cell to be on the safe side, and in each opening the largest axis-parallel rectangle is used.
HOLE_CELL = 1.0
HOLE_MIN = 12.0           # an opening narrower than this (after the host's room) holds nothing useful


class Plate(list):
    """A plate's parts [(part, x, y, turned)], with `nested`: {name of a part: name of the part whose opening it
    stands in} (2026-11-23: the report says so, and a refused slice tries again without nesting)."""
    nested: dict = {}


def _largest_rect(free: np.ndarray) -> tuple | None:
    """(r0, r1, c0, c1) of the largest all-True rectangle in a 2D bool grid (rows r0..r1-1, columns c0..c1-1)."""
    best, out = 0, None
    h = np.zeros(free.shape[1], dtype=int)
    for r in range(free.shape[0]):
        h = np.where(free[r], h + 1, 0)
        stack: list = []                                  # the largest rectangle under the histogram h
        for c in range(len(h) + 1):
            cur = h[c] if c < len(h) else 0
            start = c
            while stack and stack[-1][1] >= cur:
                s, height = stack.pop()
                if height * (c - s) > best:
                    best, out = height * (c - s), (r - height + 1, r + 1, s, c)
                start = s
            stack.append((start, cur))
    return out


def openings(p: Part) -> list[tuple]:
    """Rectangles (x0, x1, y0, y1) in mm, around the same centre as footprint(), where nothing of the part (or the
    parts merged into it) lies at any height, inside its outline. Kept with the part (copies share it); [] for a part
    without such an opening. Cheap for most parts: only one at least 3 × HOLE_MIN wide each way is drawn."""
    if p.opening is not None and p.opening[0] is p.an.rot:
        return p.opening[1]
    out: list = []
    if min(p.an.size_xy) >= 3 * HOLE_MIN:
        from scipy import ndimage
        meshes = [p.mesh] + [e.mesh for e, _ in p.extras]
        v_all = np.vstack([m.verts @ p.an.rot.T for m in meshes])
        ctr = (v_all.min(axis=0) + v_all.max(axis=0)) / 2
        lo = v_all[:, :2].min(axis=0) - ctr[:2] - 2 * HOLE_CELL
        shape = tuple(int(n) for n in np.ceil((v_all[:, :2].max(axis=0) - ctr[:2] - lo) / HOLE_CELL) + 3)
        occ = np.zeros(shape, dtype=bool)                 # [ix, iy]
        for m in meshes:
            tri = ((m.verts @ p.an.rot.T)[:, :2] - ctr[:2] - lo)[m.faces] / HOLE_CELL   # (f, 3, 2) in cells
            # upright faces add nothing to the top view (the faces above and below cover it): left out, which halves
            # the work (2026-11-23: 1.6 s for the CB cap's 20 000 faces before these two changes)
            e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
            tri = tri[np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]) > 1e-9]
            # samples at most a cell apart: a cell between them is filled by the one-cell growth below
            span = np.ptp(tri, axis=1).max(axis=1)
            steps = np.ceil(span).clip(1).astype(int)
            for n in np.unique(steps):
                sel = tri[steps == n]
                i, j = np.mgrid[0:n + 1, 0:n + 1]
                keep = i + j <= n
                a, b = (i[keep] / n), (j[keep] / n)
                pts = (sel[:, None, 0] * (1 - a - b)[None, :, None] + sel[:, None, 1] * a[None, :, None]
                       + sel[:, None, 2] * b[None, :, None]).reshape(-1, 2)
                ix = np.clip(pts[:, 0].astype(int), 0, shape[0] - 1)
                iy = np.clip(pts[:, 1].astype(int), 0, shape[1] - 1)
                occ[ix, iy] = True
        occ = ndimage.binary_dilation(occ, iterations=1)  # thin walls between samples, and a cell of safety
        inside = ndimage.binary_fill_holes(occ) & ~occ
        lab, n = ndimage.label(inside)
        for k in range(1, n + 1):
            r = _largest_rect(lab == k)
            if r is None:
                continue
            x0, x1 = lo[0] + r[0] * HOLE_CELL, lo[0] + r[1] * HOLE_CELL
            y0, y1 = lo[1] + r[2] * HOLE_CELL, lo[1] + r[3] * HOLE_CELL
            if min(x1 - x0, y1 - y0) >= HOLE_MIN:
                out.append((float(x0), float(x1), float(y0), float(y1)))
        out.sort(key=lambda o: -(o[1] - o[0]) * (o[3] - o[2]))
    p.opening = (p.an.rot, out)
    return out


def _fill(items: list, zones: list, bounds: tuple, fx: bool, fy: bool) -> tuple[list, list]:
    """One plate by _place, in order, from the corner set by fx/fy (mirrored in X/Y: fx=fy=False is back-left).
    Parts that do not fit are skipped, so smaller ones can still use the room. items: [(part, ways)], a way
    (w, d, turned, slot outline, zone outline, edge room, openings); zones: (x0, x1, y0, y1). Returns
    ([(part, (x, y), turned, way, host)], [items left over]), (x, y) the centre of the part's bounding box on the
    plate, host the part whose opening it stands in (None: on the plate). A part tries the openings of the parts
    already placed first (2026-11-23), then the plate; nest=False leaves the openings out."""
    bx0, bx1, by0, by1 = bounds

    def back(c):                                          # a centre in the mirrored plate -> on the plate
        return (bx0 + bx1 - c[0] if fx else c[0], by0 + by1 - c[1] if fy else c[1])

    mz = [_mirror(outline_rect(*z), fx, fy) + (_U @ np.array([bx0 + bx1 if fx else 0.0, by0 + by1 if fy else 0.0]))
          for z in zones]
    placed, done, rest = [], [], []
    holes: list = []                                      # [host, rectangle in the mirrored plate, [(slot, centre)]]
    for p, ways in items:
        spot = None
        for hole in holes:                                # an opening of a part already on the plate
            for way in ways:
                f, z = _mirror(way[3], fx, fy), _mirror(way[4], fx, fy)
                c = _place(f, z, hole[2], [], hole[1])
                if c is not None:
                    hole[2].append((f, c))
                    spot = (p, back(c), way[2], way, hole[0])
                    break
            if spot:
                break
        if spot is None:
            for way in ways:
                f, z = _mirror(way[3], fx, fy), _mirror(way[4], fx, fy)
                e = way[5] if len(way) > 5 else (0.0, 0.0, 0.0, 0.0)
                e = ((e[1], e[0]) if fx else (e[0], e[1])) + ((e[3], e[2]) if fy else (e[2], e[3]))   # mirrored
                c = _place(f, z, placed, mz, bounds, e)
                if c is not None:
                    placed.append((f, c))
                    spot = (p, back(c), way[2], way, None)
                    for x0, x1, y0, y1 in (way[6] if len(way) > 6 else ()):   # its openings, mirrored as the plate
                        x0, x1 = (-x1, -x0) if fx else (x0, x1)
                        y0, y1 = (-y1, -y0) if fy else (y0, y1)
                        holes.append([p, (c[0] + x0, c[0] + x1, c[1] + y0, c[1] + y1), []])
                    break
        if spot is None:
            rest.append((p, ways))
        else:
            done.append(spot)
    return done, rest


def _centre(placed: list, zones: list, bounds: tuple) -> list:
    """The filled plate moved as one block towards the middle of `bounds` (2026-11-23, user's wish: parts in the
    middle of the plate, but never fewer on it). The fill decided what goes on the plate; moving all parts together
    keeps their spacing, so nothing is lost. The block stays inside the bounds (each part's slot) and clear of the
    zones (prime tower, no-go strips), tested as _place does. Of the shifts on the way to the middle, and the X-only
    and Y-only ones, the one ending closest to the middle wins; none fits: the plate stays as it was.
    placed: [(part, (x, y), turned, way, host)] as _fill gives them, way[3] the slot outline, way[4] the zone
    outline. Parts in an opening move with their host."""
    if not placed:
        return placed
    bx0, bx1, by0, by1 = bounds
    cs = np.array([c for _, c, *_ in placed], dtype=float)
    fs = [it[3][3] for it in placed]
    es = [it[3][5] if len(it[3]) > 5 else (0.0,) * 4 for it in placed]   # extra edge room per side (pack)
    # the shift range that keeps every slot on the plate, and the block's own box
    lo = np.max([[bx0 + f[K_DIRS // 2] + e[0] - c[0], by0 + f[3 * K_DIRS // 4] + e[2] - c[1]]
                 for f, c, e in zip(fs, cs, es)], axis=0)
    hi = np.min([[bx1 - f[0] - e[1] - c[0], by1 - f[K_DIRS // 4] - e[3] - c[1]]
                 for f, c, e in zip(fs, cs, es)], axis=0)
    if np.any(lo > hi + _EPS):
        return placed
    x0 = min(c[0] - f[K_DIRS // 2] for f, c in zip(fs, cs))
    x1 = max(c[0] + f[0] for f, c in zip(fs, cs))
    y0 = min(c[1] - f[3 * K_DIRS // 4] for f, c in zip(fs, cs))
    y1 = max(c[1] + f[K_DIRS // 4] for f, c in zip(fs, cs))
    goal = np.array([(bx0 + bx1 - x0 - x1) / 2, (by0 + by1 - y0 - y1) / 2])
    goal = np.clip(goal, lo, np.maximum(lo, hi))
    if np.hypot(*goal) < 0.5:                             # already in the middle
        return placed
    # per part and zone: where the part's centre may not go (zone + its turned outline), as in _place
    nfp = [(i, outline_rect(*zn) + _neg(it[3][4])) for zn in zones for i, it in enumerate(placed)]

    def free(s) -> bool:
        for i, h in nfp:
            if np.all((cs[i] + s) @ _U.T < h - 1e-4):
                return False
        return True
    steps = np.linspace(1.0, 0.0, 41)[:-1]
    cands = [goal * a for a in steps] + [np.array([goal[0] * a, 0.0]) for a in steps] + \
        [np.array([0.0, goal[1] * a]) for a in steps]
    cands.sort(key=lambda s: float(np.hypot(*(goal - s))))
    shift = next((s for s in cands if free(s)), None)
    if shift is None or np.hypot(*shift) < 0.5:
        return placed
    return [(p, (c[0] + float(shift[0]), c[1] + float(shift[1])), *rest) for p, c, *rest in placed]


def support_room(p: Part, level: int) -> float:
    """Free room per side for a part with tree support. Level 0 is the fixed SUPPORT_ROOM; from level 1 the room
    follows the part's height (tree support spreads further from a taller part: 9.6 mm for the 50 mm CB cap), and
    level 2 halves it. The slice check in build() steps back a level when Bambu Studio objects."""
    if level == 0:
        return SUPPORT_ROOM
    room = min(SUPPORT_ROOM, max(1.5, 0.1 * p.an.height))
    return room / 2 if level >= 2 else room


def _plates(items: list, zones: list, bounds: tuple, t) -> list[list]:
    """Plates, filled in the order of `items` ([(part, ways)]): [[(part, x_center, y_center, turned)]]."""
    out, todo = [], items
    while todo:
        # each plate from all four corners (the prime tower and no-go strips sit near one corner, so filling from
        # back-left can push a large part into the middle, 2026-11-17); keep the fill that places the most area
        best = None
        for fx in (False, True):
            for fy in (False, True):
                placed, rest = _fill(todo, zones, bounds, fx, fy)
                area = sum(it[3][0] * it[3][1] for it in placed)
                if best is None or area > best[0] + 1e-6:
                    best = (area, placed, rest)
        _, placed, rest = best
        placed = _centre(placed, zones, bounds)              # the filled plate towards the middle (2026-11-23)
        if not placed:                                       # the next part does not fit even on an empty plate
            p, ways = todo[0]
            rest = todo[1:]
            if t.tower:                                      # only the prime tower's spot is in the way?
                placed, _ = _fill([todo[0]], list(t.keep_out), bounds, False, False)
                if placed:
                    p.warnings.append(tr("w.tower"))
            if not placed:                                   # too large or blocked by the no-go zones
                w, d, turn = ways[0][:3]
                placed = [(p, (bounds[0] + w / 2, bounds[3] - d / 2), turn)]
                p.warnings.append(tr("w.no_spot"))
        plate = Plate((p, c[0], c[1], turn) for p, c, turn, *_ in placed)
        plate.nested = {it[0].name: it[4].name for it in placed if len(it) > 4 and it[4] is not None}
        out.append(plate)
        todo = rest
    return out


def colour_changes(plates: list[list]) -> float:
    """How much colour changing the plates need, in mm of print height: on each layer the printer goes through every
    filament still printing at that height, so per plate the sum of the tallest part per filament minus the tallest
    part. A plate in one colour costs 0. Merged parts with their own filament count with their host's height."""
    total = 0.0
    for items in plates:
        top: dict[int, float] = {}
        for p, *_ in items:
            for f in [p.filament] + [f for _, f in p.extras]:
                top[f] = max(top.get(f, 0.0), p.an.height)
        if top:
            total += sum(top.values()) - max(top.values())
    return total


def _colour_orders(items: list) -> list[list]:
    """Other orders to fill the plates in, so that parts of one colour come together: by colour (the colour with the
    most area first, inside it largest first as before), and for each colour that colour first, the rest as before."""
    area = lambda it: max(it[1][0][0] * it[1][0][1], 0)  # noqa: E731
    by: dict[int, list] = {}
    for it in items:                                      # items are largest first already
        by.setdefault(it[0].filament, []).append(it)
    groups = sorted(by.values(), key=lambda g: -sum(area(it) for it in g))
    orders = [[it for g in groups for it in g]]
    for g in groups:
        ids = {id(it) for it in g}
        orders.append(g + [it for it in items if id(it) not in ids])
    return orders


def pack(parts: list[Part], t: Template, level: int = 0) -> list[tuple[str, list]]:
    """Bottom-left fill, all parts together; with several filaments the fill with the fewest colour changes within the
    same number of plates (or up to t.max_plates), see colour_changes. Returns plates as (name, [(part, x_center,
    y_center, turned)]).
    level: 0 safe room (the old rules), 1 support room by part height, 2 tighter: half that room, 2 mm bed margin."""
    margin = 2.0 if level >= 2 else MARGIN
    # which sides of the area packed on are a nozzle's limit inside the plate, not the plate's own edge (2026-11-23)
    boxes = list(t.nozzle_boxes) or [(t.bed_x[0], t.bed_x[1], t.bed_y[0], t.bed_y[1])]
    plate = (min(b[0] for b in boxes), max(b[1] for b in boxes), min(b[2] for b in boxes), max(b[3] for b in boxes))
    inner = (t.bed_x[0] > plate[0] + 0.5, t.bed_x[1] < plate[1] - 0.5,
             t.bed_y[0] > plate[2] + 0.5, t.bed_y[1] < plate[3] - 0.5)
    plates = []
    groups: dict[str, list[Part]] = {"all parts": list(parts)} if parts else {}
    for cname, ps in groups.items():
        items = []
        for p in ps:
            # brims of neighbours may overlap (2026-11-20): a brim claims one brim width between two
            # parts, not two; the room for tree support stays full on both sides
            sup = p.settings.get("enable_support") == "1"
            pad = max(p.brim, 2 * support_room(p, level) if sup else 0.0)
            # 2026-11-23: at the tight level parts may stand closer together, but a part with tree support keeps
            # level 1's room to the edge of a nozzle's area inside the plate: its support spreads ~10 mm from a 50 mm
            # part, and past that edge Bambu Studio refuses the slice ("Found G-code in unprintable area of
            # multi-extruder printers", the Lid with Nozzle left: the CB cap at x 325 sent it back to 2 plates). At
            # the plate's own edges Bambu Studio did not object, so there it stays tight
            edge = (0.0, 0.0, 0.0, 0.0)
            if sup and level >= 2:
                extra = support_room(p, 1) - support_room(p, level) + (MARGIN - margin)
                edge = tuple(extra if side else 0.0 for side in inner)
            w, d = (s + pad + GAP for s in p.an.size_xy)
            h = footprint(p)
            # slot: outline + half the gap and half the pad; for the zones: outline + half the pad + 1 mm (as before)
            # its openings (2026-11-23): less its own room (half the gap and half the pad, as its slot outside);
            # turned a quarter as the part: (x, y) -> (-y, x). t.nest False (a refused slice): none
            room = (pad + GAP) / 2
            ops = [(x0 + room, x1 - room, y0 + room, y1 - room) for x0, x1, y0, y1 in
                   (openings(p) if getattr(t, "nest", True) else [])]
            ops = [o for o in ops if min(o[1] - o[0], o[3] - o[2]) >= HOLE_MIN]
            plain = (w, d, False, h + (pad + GAP) / 2, h + pad / 2 + 1, edge, ops)
            turned = (d, w, True, _quarter(plain[3]), _quarter(plain[4]), edge,
                      [(-y1, -y0, x0, x1) for x0, x1, y0, y1 in ops])
            # both ways round, the long side along X first; _place takes the first that fits
            ways = [plain, turned] if w >= d else [turned, plain]
            items.append((p, ways))
        items.sort(key=lambda it: -max(it[1][0][0] * it[1][0][1], 0))   # largest first
        # the prime tower's spot stays free whenever the process has it on: Bambu Studio may print it with one
        # filament too (H2D, two nozzles), and a part there fails the slice ("G-code conflicts", 2026-11-17)
        zones = list(t.keep_out) + ([t.tower] if t.tower else [])
        # slots include half the gap and half the brim (shared with a neighbour). At level 2 (2 mm bed margin) a wide
        # brim may reach past the bed edge; that layout is only kept when Bambu Studio slices it clean (build steps
        # back otherwise). Shrinking the bed for every part instead cost a plate on a layout that sliced clean.
        bounds = (t.bed_x[0] + margin - GAP / 2, t.bed_x[1] - margin + GAP / 2,
                  t.bed_y[0] + margin - GAP / 2, t.bed_y[1] - margin + GAP / 2)
        w0 = {id(p): list(p.warnings) for p in ps}
        best = _plates(items, zones, bounds, t)
        fils = {p.filament for p in ps} | {f for p in ps for _, f in p.extras}
        if len(fils) > 1:
            # several colours (2026-11-23): the same number of plates, or up to "max plates" when the user allows
            # more, with as few colour changes as the parts allow (same-colour parts on one plate: a smaller prime
            # tower, less purge, time and filament). A change of less than 1 mm of height does not count.
            allowed = max(len(best), t.max_plates or 0)
            best_w = {id(p): list(p.warnings) for p in ps}
            score = (colour_changes(best), len(best))
            for order in _colour_orders(items):
                for p in ps:                                  # each try starts from the same warnings
                    p.warnings[:] = w0[id(p)]
                try_ = _plates(order, zones, bounds, t)
                s = (colour_changes(try_), len(try_))
                if len(try_) <= allowed and (s[0] < score[0] - 1.0 or (s[0] <= score[0] + 1.0 and s[1] < score[1])):
                    best, score, best_w = try_, s, {id(p): list(p.warnings) for p in ps}
            for p in ps:
                p.warnings[:] = best_w[id(p)]
        plates += [(cname, items_) for items_ in best]
    counts: dict[str, int] = {}
    for c, _ in plates:
        counts[c] = counts.get(c, 0) + 1
    named, seen = [], {}
    for c, items in plates:
        seen[c] = seen.get(c, 0) + 1
        named.append((c if counts[c] == 1 else f"{c} {seen[c]}", items))
    return named


def pack_nozzles(parts: list[Part], t: Template, level: int = 0, skip=frozenset()) -> list[tuple[str, list]]:
    """pack() on the area every nozzle reaches; with one filament on a printer with 2+ nozzles, also on each nozzle's
    own (larger) area, and keep that when it needs fewer plates. The filament is then fixed to that nozzle
    (t.nozzle, written as filament_map in write_3mf), as parts/print_plate.py of the models did (
    2026-11-17: use the left nozzle's range too). skip: nozzles (1-based) whose area Bambu Studio refused at this
    level, with Nozzle auto (2026-11-23: left and right tied at 1 plate, left was refused, the build stepped back to
    2 plates although right sliced)."""
    warn0 = {id(p): list(p.warnings) for p in parts}
    best = pack(parts, t, level)
    if t.filaments != 1 or len(t.nozzle_boxes) < 2:
        return best
    best_warn = {id(p): list(p.warnings) for p in parts}
    shared = (t.bed_x, t.bed_y)
    pick = None
    # widest area first: on a tie in plates the earlier (larger) one wins
    order = sorted(range(len(t.nozzle_boxes)),
                   key=lambda i: -(t.nozzle_boxes[i][1] - t.nozzle_boxes[i][0]) * (t.nozzle_boxes[i][3] - t.nozzle_boxes[i][2]))
    forced = {"left": 0, "right": 1}.get(t.nozzle_mode)
    if forced is not None:                                  # menu: that nozzle only, even when it needs more plates
        order = [forced]
        best = None
    for i in order:
        if forced is None and i + 1 in skip:
            continue
        x0, x1, y0, y1 = t.nozzle_boxes[i]
        t.bed_x, t.bed_y = (x0, x1), (y0, y1)
        for p in parts:
            p.warnings[:] = warn0[id(p)]
        plates = pack(parts, t, level)
        if best is None or len(plates) < len(best):
            best, pick, best_warn = plates, (i, (x0, x1), (y0, y1)), {id(p): list(p.warnings) for p in parts}
    for p in parts:
        p.warnings[:] = best_warn[id(p)]
    if pick is None:
        t.bed_x, t.bed_y = shared
    else:
        t.nozzle, t.bed_x, t.bed_y = pick[0] + 1, pick[1], pick[2]
    return best


def pack_auto(parts: list[Part], t: Template, level: int | None = None, skip=frozenset()) -> tuple[list, int]:
    """_pack_auto, with parts in openings of other parts unless skip holds "no-nest" (2026-11-23: retry_layout adds it
    when Bambu Studio refused a layout with nested parts). t.nested: whether the result has any."""
    t.nest = "no-nest" not in skip
    plates, level = _pack_auto(parts, t, level, frozenset(s for s in skip if s != "no-nest"))
    t.nested = any(getattr(items, "nested", None) for _, items in plates)
    return plates, level


def _pack_auto(parts: list[Part], t: Template, level: int | None = None, skip=frozenset()) -> tuple[list, int]:
    """(plates, level). A given level is used as is. Otherwise: level 1 (support room by part height), and when that
    needs more than one plate level 2 (tighter) too, kept only when it needs fewer plates. skip: see pack_nozzles."""
    if level is not None:
        return pack_nozzles(parts, t, level, skip), level
    state = (t.bed_x, t.bed_y, t.nozzle, {id(p): list(p.warnings) for p in parts})

    def restore():
        t.bed_x, t.bed_y, t.nozzle = state[:3]
        for p in parts:
            p.warnings[:] = state[3][id(p)]

    best = 1
    count = len(pack_nozzles(parts, t, 1, skip))
    restore()
    if count > 1:
        if len(pack_nozzles(parts, t, 2, skip)) < count:
            best = 2
        restore()
    return pack_nozzles(parts, t, best, skip), best


# --- template age -------------------------------------------------------------------------------------------------
def _version(s: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", s or ""))


def model_title(ws: Path) -> str:
    try:
        return json.loads((ws / ".soma" / "project.json").read_text(encoding="utf-8")).get("name", ws.name)
    except (OSError, ValueError):
        return ws.name


def soma_models() -> list[tuple[str, Path]]:
    """(name, folder) of every SOMA model on this PC, most recently changed first."""
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "soma" / "workspaces"
    found = []
    for pj in root.glob("*/.soma/project.json"):
        try:
            found.append((pj.stat().st_mtime, model_title(pj.parent.parent), pj.parent.parent))
        except OSError:
            continue
    return [(n, f) for _, n, f in sorted(found, key=lambda x: x[0], reverse=True)]


def shown_path(p) -> str:
    """A path as the report shows it (2026-11-22): testers attach the report to issues, so no Windows user name in it.
    A template of the tool as 'templates/default.3mf', one in the user folder as '%USERPROFILE%\\...'."""
    p = Path(p)
    try:
        return p.resolve().relative_to(TOOL_DIR).as_posix()
    except (OSError, ValueError):
        pass
    home = str(Path.home())
    s = str(p)
    return "%USERPROFILE%" + s[len(home):] if s.lower().startswith(home.lower() + os.sep) else s


MAX_COPIES = 200          # duplicates of the whole set, and copies of one part (2026-11-21: both,
                          # 2026-11-22: up to 200, with the guard in orientr.py against projects too big for Bambu Studio)


                           # of memory while it loads or slices
MAX_PLATES = 50


def strict_number(v, what: str, percent: bool = False) -> float:
    """A finite number from bambu.json, or a ToolError naming the field (never a silent 0)."""
    s = str(v).strip()
    if percent and s.endswith("%"):
        s = s[:-1].strip()
    try:
        x = float(s)
    except ValueError:
        raise ToolError(f'{what} must be a number, not {v!r}') from None
    if not math.isfinite(x) or isinstance(v, bool):
        raise ToolError(f'{what} must be a number, not {v!r}')
    return x


def whole_number(v, what: str, lo: int, hi: int) -> int:
    """A whole number lo..hi from bambu.json or the command line, or a ToolError naming the field."""
    x = strict_number(v, what)
    if x != int(x) or not lo <= x <= hi:
        raise ToolError(f"{what} must be a whole number {lo}..{hi}, not {v!r}")
    return int(x)


class PreviewStopped(Exception):
    """Esc while Bambu Studio slices for the Preview."""
