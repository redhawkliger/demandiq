"""
DemandIQ Forecasting — canonical link contract.

The foundational deep module for Method 1 (NCHRP 765 model-based forecasting).
Every region adapter (SANDAG, and any future region) emits a NetworkLayer of
these links; the link-to-leg matcher and the NCHRP 255 refinement step both
consume them.

Design notes (locked with Akshaey):
  - The AB/BA inbound-read convention is encoded EXACTLY ONCE, as a method on
    NetworkLink (inbound_to / outbound_from). Nothing downstream re-derives it.
  - Shared metadata (region, CRS, scenario_year) lives on the NetworkLayer
    envelope — single source of truth. A NetworkLink is therefore mono-year and
    LAYER-SCOPED, not self-contained: detach it from its layer and it no longer
    knows its year or CRS. When persisting a match, store (scenario_year,
    link_id) and re-resolve against the layer rather than holding a loose link.
  - Geometry arrives ALREADY reprojected to the project map CRS — the adapter
    owns the EPSG:2230 → project-CRS transform so nothing here reprojects.
  - One NetworkLayer = one scenario-year. Base and horizon are two layers;
    NCHRP 255 refinement joins them by link_id (hence the uniqueness validator).
"""

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class Period(str, Enum):
    """SANDAG loaded-network time periods."""
    EA = "EA"   # early AM
    AM = "AM"   # AM peak
    MD = "MD"   # midday
    PM = "PM"   # PM peak
    EV = "EV"   # evening


# A vertex in the PROJECT map CRS — already reprojected by the adapter.
Coord = tuple[float, float]


class DirectionalFlow(BaseModel):
    """A model link's volumes for ONE scenario-year, both travel directions.

    AB = digitized direction (from_node → to_node); BA = against it. A period
    may be absent if the source network doesn't publish it.
    """
    model_config = {"extra": "forbid"}
    ab: dict[Period, float] = Field(default_factory=dict)
    ba: dict[Period, float] = Field(default_factory=dict)


class NetworkLink(BaseModel):
    """One model link within a NetworkLayer. Mono-year: its scenario_year,
    region, and CRS come from the enclosing layer. Geometry coords are in the
    layer's crs_epsg.
    """
    model_config = {"extra": "forbid"}

    # ── Identity & topology ──────────────────────────────────────────────────
    link_id: str
    from_node: int               # AB tail
    to_node: int                 # AB head

    # ── Geometry (in the layer's crs_epsg) ───────────────────────────────────
    geometry: list[Coord]        # LineString, from_node → to_node order
    from_node_xy: Coord          # node snap targets for the matcher
    to_node_xy: Coord
    # Canonical link length in MILES — the adapter computes it (model-native field
    # if present, else great-circle from geometry) so the engine never re-derives
    # length from region-specific source columns. None only on hand-built links.
    length_mi: float | None = None

    # ── Classification (match-review sanity, e.g. don't bind freeway↔arterial) ─
    name: str | None = None
    functional_class: str | None = None   # adapter-normalized
    lanes: int | None = None

    # ── Volumes (for the layer's scenario_year) ──────────────────────────────
    flow: DirectionalFlow
    # Canonical model DAILY total volume (both directions, all periods) — the
    # adapter populates it so VMT's daily ratio reads the contract, not a
    # region-specific column name. None when the source model has no daily total.
    daily_total: float | None = None

    # ── Provenance — the raw source row stays per-link ───────────────────────
    source_attributes: dict[str, str | float | int | None] = Field(default_factory=dict)

    # ── AB/BA convention — lives here, nowhere else ──────────────────────────
    def inbound_to(self, node: int) -> dict[Period, float]:
        """Per-period volume ENTERING `node` on this link.
        AB if to_node == node; BA if from_node == node."""
        if node == self.to_node:
            return self.flow.ab
        if node == self.from_node:
            return self.flow.ba
        raise ValueError(f"node {node} not an endpoint of link {self.link_id}")

    def outbound_from(self, node: int) -> dict[Period, float]:
        """Per-period volume LEAVING `node` on this link (mirror of inbound_to)."""
        if node == self.from_node:
            return self.flow.ab
        if node == self.to_node:
            return self.flow.ba
        raise ValueError(f"node {node} not an endpoint of link {self.link_id}")


class NetworkLayer(BaseModel):
    """A region's model network for ONE scenario-year, in the project map CRS."""
    model_config = {"extra": "forbid"}
    region: str                  # 'SANDAG'
    source_crs_epsg: int         # 2230
    crs_epsg: int                # project map CRS after reprojection
    scenario_year: int           # 2025, 2030, etc.
    links: list[NetworkLink]

    @model_validator(mode="after")
    def _unique_link_ids(self):
        """link_id must be unique within a layer — refinement pairs base↔future
        layers by link_id, so a collision is a correctness bug, not cosmetics."""
        ids = [l.link_id for l in self.links]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate link_id(s) in layer: {dupes}")
        return self
