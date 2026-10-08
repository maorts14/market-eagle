"""Generate the editable Market Eagle architecture workbook for diagrams.net."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET


OUT = Path(__file__).with_name("market-eagle-architecture.drawio")

COLORS = {
    "ink": "#15263B",
    "muted": "#61758A",
    "line": "#9CB0C3",
    "blue": "#EAF2FF",
    "blue_edge": "#3E78C7",
    "teal": "#E8F7F3",
    "teal_edge": "#2B967F",
    "purple": "#F1EEFB",
    "purple_edge": "#7863B0",
    "amber": "#FFF5DF",
    "amber_edge": "#B77924",
    "gray": "#F3F6F9",
    "gray_edge": "#9DAFBE",
    "white": "#FFFFFF",
}

file = ET.Element("mxfile", {
    "host": "app.diagrams.net",
    "agent": "Codex architecture generator",
    "type": "device",
})


class Page:
    def __init__(self, page_id: str, name: str, title: str, subtitle: str):
        diagram = ET.SubElement(file, "diagram", {"id": page_id, "name": name})
        model = ET.SubElement(diagram, "mxGraphModel", {
            "dx": "1600", "dy": "950", "grid": "0", "guides": "1",
            "tooltips": "1", "connect": "1", "arrows": "1", "fold": "1",
            "page": "1", "pageScale": "1", "pageWidth": "1600",
            "pageHeight": "950", "math": "0", "shadow": "0",
        })
        self.root = ET.SubElement(model, "root")
        ET.SubElement(self.root, "mxCell", {"id": "0"})
        ET.SubElement(self.root, "mxCell", {"id": "1", "parent": "0"})
        self.ids = {"0", "1"}
        self.box("masthead", 0, 0, 1600, 14, "", "ink", "ink", radius=0)
        self.label("title", 60, 40, 1450, 48, title, 30, "ink", bold=True)
        self.label("subtitle", 60, 94, 1460, 42, subtitle, 15, "muted")
        self.box("divider", 60, 146, 1480, 2, "", "gray_edge", "gray_edge", radius=0)

    def add(self, ident: str, *, value: str, style: str, x: int, y: int,
            w: int, h: int) -> None:
        if ident in self.ids:
            raise ValueError(f"Duplicate cell ID: {ident}")
        self.ids.add(ident)
        cell = ET.SubElement(self.root, "mxCell", {
            "id": ident, "value": value, "style": style, "vertex": "1",
            "parent": "1",
        })
        ET.SubElement(cell, "mxGeometry", {
            "x": str(x), "y": str(y), "width": str(w), "height": str(h),
            "as": "geometry",
        })

    def box(self, ident: str, x: int, y: int, w: int, h: int, value: str,
            fill: str, stroke: str, *, radius: int = 14, dashed: bool = False,
            size: int = 18, align: str = "center") -> None:
        style = (
            f"rounded={1 if radius else 0};arcSize={radius};whiteSpace=wrap;html=1;"
            f"fillColor={COLORS.get(fill, fill)};strokeColor={COLORS.get(stroke, stroke)};"
            f"strokeWidth=1.5;fontFamily=Arial;fontSize={size};fontColor={COLORS['ink']};"
            f"align={align};verticalAlign=middle;spacing=12;"
        )
        if dashed:
            style += "dashed=1;dashPattern=7 5;"
        self.add(ident, value=value, style=style, x=x, y=y, w=w, h=h)

    def card(self, ident: str, x: int, y: int, w: int, h: int, title: str,
             detail: str, fill: str = "blue", stroke: str = "blue_edge",
             *, status: str = "", dashed: bool = False,
             icon: str | None = None) -> None:
        status_line = f"<br><font color='{COLORS['muted']}'>{status}</font>" if status else ""
        value = (
            f"<b>{title}</b><br><font color='{COLORS['muted']}'>{detail}</font>"
            f"{status_line}"
        )
        if icon is None:
            self.box(ident, x, y, w, h, value, fill, stroke, size=17, dashed=dashed)
            self.root[-1].set("style", self.root[-1].get("style", "") + "card=1;")
            return
        self.box(ident, x, y, w, h, "", fill, stroke, dashed=dashed)
        self.root[-1].set("style", self.root[-1].get("style", "") + "card=1;")
        self.icon(f"{ident}_icon", icon, x + 12, y + (h - 36) // 2,
                  COLORS.get(stroke, stroke))
        self.add(f"{ident}_text", value=value,
                 style=("text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;"
                        f"fontFamily=Arial;fontSize=16;fontColor={COLORS['ink']};"
                        "align=left;verticalAlign=middle;spacing=0;"),
                 x=x + 56, y=y + 6, w=w - 64, h=h - 12)

    def icon(self, ident: str, kind: str, x: int, y: int, color: str) -> None:
        def part(suffix: str, shape: str, px: int, py: int, w: int, h: int,
                 fill: str = "none", rounded: bool = False) -> None:
            self.add(f"{ident}_{suffix}", value="",
                     style=(f"shape={shape};rounded={int(rounded)};html=1;"
                            f"fillColor={fill};strokeColor={color};strokeWidth=2;"),
                     x=px, y=py, w=w, h=h)

        if kind == "person":
            part("actor", "umlActor", x + 4, y, 28, 36)
        elif kind == "database":
            part("cylinder", "cylinder", x + 2, y + 2, 32, 32, "#FFFFFF")
        elif kind == "server":
            for i in range(3):
                part(f"rack_{i}", "rectangle", x + 1, y + 3 + i * 11,
                     34, 9, "#FFFFFF", rounded=True)
                part(f"light_{i}", "ellipse", x + 6, y + 6 + i * 11,
                     3, 3, color)
        elif kind == "monitor":
            part("screen", "rectangle", x + 1, y + 2, 34, 24, "#FFFFFF", rounded=True)
            part("stem", "rectangle", x + 16, y + 26, 4, 6, color)
            part("base", "rectangle", x + 9, y + 32, 18, 3, color)
        elif kind == "chart":
            part("axis", "rectangle", x + 2, y + 31, 33, 2, color)
            for i, top in enumerate((18, 11, 4)):
                part(f"bar_{i}", "rectangle", x + 5 + i * 10, y + top,
                     6, 31 - top, color)
        elif kind == "clock":
            part("face", "ellipse", x + 2, y + 2, 32, 32, "#FFFFFF")
            part("hand_up", "rectangle", x + 17, y + 9, 2, 12, color)
            part("hand_right", "rectangle", x + 18, y + 19, 9, 2, color)
        elif kind == "cloud":
            part("cloud", "cloud", x + 1, y + 5, 34, 26, "#FFFFFF")
        else:
            raise ValueError(f"Unknown icon kind: {kind}")

    def label(self, ident: str, x: int, y: int, w: int, h: int, value: str,
              size: int = 16, color: str = "ink", *, bold: bool = False,
              align: str = "left") -> None:
        style = (
            f"text;html=1;whiteSpace=wrap;strokeColor=none;fillColor=none;"
            f"fontFamily=Arial;fontSize={size};fontColor={COLORS.get(color, color)};"
            f"fontStyle={1 if bold else 0};align={align};verticalAlign=middle;"
        )
        self.add(ident, value=value, style=style, x=x, y=y, w=w, h=h)

    def group(self, ident: str, x: int, y: int, w: int, h: int, title: str,
              *, fill: str = "gray", dashed: bool = False) -> None:
        self.box(ident, x, y, w, h, "", fill, "gray_edge", dashed=dashed)
        self.label(f"{ident}_title", x + 20, y + 8, w - 40, 30, title,
                   15, "muted", bold=True)

    def edge(self, ident: str, source: str, target: str, label: str = "",
             *, color: str = "line", dashed: bool = False,
             exit_x: float | None = None, exit_y: float | None = None,
             entry_x: float | None = None, entry_y: float | None = None,
             waypoints: list[tuple[int, int]] | None = None,
             arrow: bool = True) -> None:
        if ident in self.ids:
            raise ValueError(f"Duplicate cell ID: {ident}")
        if source not in self.ids or target not in self.ids:
            raise ValueError(f"Unknown edge endpoint: {source} -> {target}")
        self.ids.add(ident)
        style = (
            "edgeStyle=orthogonalEdgeStyle;orthogonalLoop=1;jettySize=auto;"
            f"rounded=1;html=1;strokeColor={COLORS.get(color, color)};"
            f"strokeWidth=2;endArrow={'block' if arrow else 'none'};"
            f"endFill=1;fontFamily=Arial;fontSize=12;fontColor={COLORS['muted']};"
            "labelBackgroundColor=#FFFFFF;"
        )
        if dashed:
            style += "dashed=1;dashPattern=7 5;"
        for name, val in (("exitX", exit_x), ("exitY", exit_y),
                          ("entryX", entry_x), ("entryY", entry_y)):
            if val is not None:
                style += f"{name}={val};"
        cell = ET.SubElement(self.root, "mxCell", {
            "id": ident, "value": label, "style": style, "edge": "1",
            "parent": "1", "source": source, "target": target,
        })
        geometry = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
        if waypoints:
            points = ET.SubElement(geometry, "Array", {"as": "points"})
            for x, y in waypoints:
                ET.SubElement(points, "mxPoint", {"x": str(x), "y": str(y)})

    def footer(self, page_no: str, note: str) -> None:
        self.box(f"footer_rule_{page_no}", 60, 870, 1480, 2, "",
                 "gray_edge", "gray_edge", radius=0)
        self.label(f"footer_note_{page_no}", 60, 884, 1300, 38,
                   note, 13, "muted")
        self.label(f"footer_page_{page_no}", 1420, 884, 120, 38,
                   page_no, 13, "muted", align="right")


# 01 — System context. External systems are amber; project system is blue.
p = Page("context", "01 · Context", "Market Eagle · system context",
         "Who uses the system, what it depends on, and the private-to-public access path.")
p.group("project_boundary", 485, 245, 635, 460, "MARKET EAGLE · product boundary", fill="gray")
p.card("researcher", 90, 330, 250, 118, "Researcher",
       "Creator first; trader design partners later", "teal", "teal_edge", icon="person")
p.card("market_eagle", 640, 345, 325, 150, "Market Eagle",
       "Explore sectors and stocks over flexible windows; later ask analytical questions",
       icon="chart")
p.card("alpaca", 1230, 225, 270, 112, "Market-data provider",
       "Alpaca Free candidate · daily OHLCV", "amber", "amber_edge", icon="cloud")
p.card("constituents", 1230, 415, 270, 112, "Constituent source",
       "S&amp;P 500 membership and sectors · FMP candidate", "amber", "amber_edge",
       icon="cloud")
p.card("model", 1230, 605, 270, 112, "Model provider",
       "Later agent interpretation and answer drafting", "purple", "purple_edge",
       icon="cloud")
p.label("context_scope", 545, 545, 520, 105,
        "Initial scope: current S&amp;P 500 members · five years of daily OHLCV · "
        "hourly and after-close refresh of one current-day candle", 16)
p.edge("ctx_user", "researcher", "market_eagle", "Tailscale first",
       color="teal_edge", exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("ctx_alpaca", "alpaca", "market_eagle", "observations",
       color="amber_edge", exit_x=0, exit_y=.5, entry_x=1, entry_y=.2)
p.edge("ctx_constituents", "constituents", "market_eagle", "membership + sectors",
       color="amber_edge", exit_x=0, exit_y=.5, entry_x=1, entry_y=.52)
p.edge("ctx_model", "market_eagle", "model", "later · model calls",
       color="purple_edge", dashed=True, exit_x=1, exit_y=.8, entry_x=0, entry_y=.5)
p.footer("01 / 07", "Solid = initial path   ·   Dashed = later or undecided   ·   Amber = external source")

# 02 — Two data paths with Temporal as a control plane.
p = Page("containers", "02 · Containers", "System paths and control plane",
         "Market data flows through ingestion into application PostgreSQL; Temporal schedules the work from above.")
p.group("control_lane", 55, 190, 1490, 145, "CONTROL PLANE · execution state, not market data", fill="gray")
p.group("collection_lane", 55, 350, 950, 240, "COLLECTION · external data to validated records", fill="gray")
p.group("research_lane", 55, 610, 950, 190, "RESEARCH · user request to calculation", fill="gray")
p.group("application_store", 1030, 350, 515, 450, "APPLICATION POSTGRESQL · canonical catalog and bars", fill="gray")
p.card("temporal", 380, 220, 300, 85, "Temporal service",
       "Schedules · retries · run status", "purple", "purple_edge", icon="clock")
p.card("temporal_sql", 1130, 220, 285, 85, "Temporal SQL",
       "Workflow history + visibility only", "purple", "purple_edge", icon="database")
p.card("catalog_source", 80, 390, 215, 80, "Catalog source",
       "Current members + sectors", "amber", "amber_edge", icon="cloud")
p.card("price_source", 80, 490, 215, 80, "Price provider",
       "Daily prices + volume", "amber", "amber_edge", icon="cloud")
p.card("catalog_worker", 350, 390, 250, 80, "Catalog ingestion",
       "Match stocks · validate changes", icon="server")
p.card("bar_worker", 350, 490, 250, 80, "Price ingestion",
       "Map ticker/date · validate bars", icon="server")
p.card("catalog_store", 1100, 390, 360, 80, "Published catalog",
       "Members + current sector per stock", "teal", "teal_edge", icon="database")
p.card("bar_store", 1100, 490, 360, 80, "Daily bar store",
       "Stored prices + corrections", "teal", "teal_edge", icon="database")
p.card("workspace", 80, 655, 215, 100, "Researcher workspace",
       "Dates + sector drilldown", icon="monitor")
p.card("api", 350, 655, 250, 100, "Application API",
       "Validate request · return results", icon="server")
p.card("analytic_service", 660, 655, 295, 100, "Analytical service",
       "Resolve closes · calculate rankings", "teal", "teal_edge", icon="chart")
p.card("read_view", 1100, 665, 360, 85, "Query inputs",
       "Published catalog + stored daily prices", "teal", "teal_edge", icon="database")
p.edge("c_temporal_sql", "temporal", "temporal_sql", "execution state",
       color="purple_edge", exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("c_temporal_collection", "temporal", "collection_lane", "starts + retries",
       color="purple_edge", exit_x=.5, exit_y=1, entry_x=.5, entry_y=0)
p.edge("c_catalog_fetch", "catalog_source", "catalog_worker",
       color="amber_edge", exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("c_catalog_write", "catalog_worker", "catalog_store", "publish snapshot",
       color="teal_edge", exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("c_price_fetch", "price_source", "bar_worker",
       color="amber_edge", exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("c_bar_write", "bar_worker", "bar_store", "validated observations",
       color="teal_edge", exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("c_workspace_api", "workspace", "api",
       exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("c_api_analytics", "api", "analytic_service",
       exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("c_analytics_read", "analytic_service", "read_view", "read-only SQL",
       color="teal_edge", exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.footer("02 / 07", "Temporal controls collection above the data path   ·   Catalog and bars share application PostgreSQL")

# 03 — Ordered catalog and price ingestion.
p = Page("collection", "03 · Collection", "Collection and ingestion",
         "Each provider response passes through validation before publication; Temporal controls runs from above.")
p.group("collection_control", 55, 190, 1490, 120, "CONTROL · schedule, retry, progress", fill="gray")
p.group("catalog_flow", 55, 325, 1490, 195, "CATALOG FLOW · current members and sectors", fill="gray")
p.group("price_flow", 55, 540, 1490, 260, "PRICE FLOW · five-year backfill, session refresh, reconciliation", fill="gray")
p.card("collection_temporal", 605, 215, 390, 75, "Temporal collection controller",
       "Starts runs · retries activities · tracks progress", "purple", "purple_edge", icon="clock")
p.card("catalog_provider", 80, 380, 200, 100, "1 · Catalog source",
       "Members + sectors", "amber", "amber_edge", icon="cloud")
p.card("catalog_fetch", 330, 380, 185, 100, "2 · Fetch rows",
       "Dated source rows", icon="server")
p.card("catalog_match", 565, 380, 240, 100, "3 · Match stock IDs",
       "Ticker/exchange → stable stock ID", icon="server")
p.card("catalog_publish", 855, 380, 240, 100, "4 · Review + publish",
       "Check changes; publish full snapshot", icon="server")
p.card("catalog_tables", 1230, 380, 280, 100, "5 · Catalog tables",
       "Snapshot · members · current sectors", "teal", "teal_edge", icon="database")
p.card("market_provider", 80, 595, 220, 100, "1 · Price provider",
       "Daily bars + feed/as-of metadata", "amber", "amber_edge", icon="cloud")
p.card("fetch_pages", 350, 595, 240, 100, "2 · Fetch all pages",
       "Bounded symbols/dates · rate limit", icon="server")
p.card("map_validate", 645, 595, 245, 100, "3 · Map + validate",
       "Ticker/date → stock ID; check prices + volume", icon="server")
p.card("write_bars", 945, 595, 230, 100, "4 · Save prices",
       "Save prices + later corrections", icon="server")
p.card("bar_tables", 1240, 595, 270, 100, "5 · Daily price database",
       "Prices + where they came from", "teal", "teal_edge", icon="database")
p.card("coverage_check", 945, 705, 565, 80, "6 · After backfill / recheck",
       "Worker queries PostgreSQL for missing requested prices; Temporal retries", icon="server")
p.edge("d_control_catalog", "collection_temporal", "catalog_flow", "start / retry",
       color="purple_edge", exit_x=.3, exit_y=1, entry_x=.3, entry_y=0)
p.edge("d_control_price", "collection_temporal", "price_flow", "start / retry",
       color="purple_edge", exit_x=.7, exit_y=1, entry_x=.728, entry_y=0,
       waypoints=[(878, 315), (1140, 315), (1140, 525)])
p.edge("d_catalog_source", "catalog_provider", "catalog_fetch",
       color="amber_edge", exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("d_catalog_match", "catalog_fetch", "catalog_match",
       exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("d_catalog_review", "catalog_match", "catalog_publish",
       exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("d_catalog_store", "catalog_publish", "catalog_tables", "snapshot",
       color="teal_edge", exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("d_price_source", "market_provider", "fetch_pages",
       color="amber_edge", exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("d_fetch_map", "fetch_pages", "map_validate",
       exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("d_map_write", "map_validate", "write_bars",
       exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("d_write_store", "write_bars", "bar_tables",
       color="teal_edge", exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("d_write_coverage", "write_bars", "coverage_check",
       exit_x=.5, exit_y=1, entry_x=.5, entry_y=0)
p.footer("03 / 07", "Current sector snapshot is published as one unit   ·   Price basis and provisional storage/selection remain open")

# 04 — Research execution and evidence.
p = Page("research", "04 · Research", "Research and agent path",
         "Both interaction modes use one calculation boundary; analytical answers come from retained observations.")
p.group("interaction", 55, 215, 295, 540, "INTERACTION", fill="gray")
p.group("interpretation", 390, 215, 320, 540, "REQUEST PLANNING", fill="gray")
p.group("analytics", 750, 215, 390, 540, "DETERMINISTIC ANALYTICS", fill="gray")
p.group("evidence", 1180, 215, 360, 540, "EVIDENCE + OUTPUT", fill="gray")
p.card("explorer_ui", 85, 295, 235, 110, "Sector explorer",
       "Date window · sector drilldown", icon="monitor")
p.card("agent_ui", 85, 560, 235, 110, "Free-text question",
       "Later research interface", "purple", "purple_edge", icon="person")
p.card("typed_plan", 420, 295, 260, 110, "Typed request",
       "Requested dates · scope · metric version")
p.card("agent_plan", 420, 560, 260, 110, "Agent interpretation",
       "PydanticAI candidate · validated plan", "purple", "purple_edge")
p.card("calculation", 780, 315, 330, 145, "Analytical query service",
       "Pin catalog · resolve two closes<br>eligible returns · breadth · rankings", "teal", "teal_edge",
       icon="chart")
p.card("read_store", 780, 575, 330, 100, "Read-only PostgreSQL",
       "Published catalog + stored daily prices", "teal", "teal_edge",
       icon="database")
p.card("results", 1210, 300, 300, 145, "Result + evidence",
       "Resolved dates · eligible counts<br>source/feed/basis · data/catalog as-of", "blue", "blue_edge")
p.card("explain", 1210, 560, 300, 110, "Agent explanation",
       "Evidence-backed summary; clarify if needed", "purple", "purple_edge")
p.edge("r_explore_plan", "explorer_ui", "typed_plan", "select",
       exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("r_plan_query", "typed_plan", "calculation", "validated",
       exit_x=1, exit_y=.5, entry_x=0, entry_y=.3)
p.edge("r_agent_plan", "agent_ui", "agent_plan", "question",
       color="purple_edge", dashed=True, exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("r_agent_query", "agent_plan", "calculation", "same contract",
       color="purple_edge", dashed=True, exit_x=1, exit_y=.3, entry_x=0, entry_y=.8)
p.edge("r_query_db", "calculation", "read_store", "set-based SQL",
       color="teal_edge", exit_x=.5, exit_y=1, entry_x=.5, entry_y=0)
p.edge("r_query_result", "calculation", "results", "computed answer",
       color="teal_edge", exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("r_evidence_explain", "results", "explain", "facts only",
       color="purple_edge", dashed=True, exit_x=.5, exit_y=1, entry_x=.5, entry_y=0)
p.footer("04 / 07", "Accepted: breadth-ranked sectors, excess-return stocks, current sector grouping   ·   Dashed: later agent path")

# 05 — Persistence is separated by owner and recoverability.
p = Page("data", "05 · Data ownership", "Data ownership and key entities",
         "Application facts and Temporal orchestration history are separate databases, even if they share a PostgreSQL server.")
p.group("catalog_group", 55, 205, 315, 590, "APPLICATION DB · CATALOG", fill="gray")
p.group("observation_group", 395, 205, 425, 590, "APPLICATION DB · OBSERVATIONS", fill="gray")
p.group("research_group", 845, 205, 330, 590, "APPLICATION DB · RESEARCH", fill="gray")
p.group("temporal_group", 1200, 205, 345, 590, "TEMPORAL-OWNED DBs", fill="gray")
p.card("entity_security", 80, 260, 265, 90, "Security + ticker history",
       "Stable ID · dated ticker aliases", "teal", "teal_edge")
p.card("entity_universe", 80, 365, 265, 90, "Universe snapshot",
       "Published members + current sector", "teal", "teal_edge")
p.card("entity_sector", 80, 470, 265, 90, "Sector history",
       "Past sector changes; not used in first rankings", "teal", "teal_edge")
p.card("entity_listing", 80, 575, 265, 90, "Listing period · proposed",
       "When a stock was tradable", "teal", "teal_edge")
p.card("entity_sessions", 80, 680, 265, 90, "Trading sessions",
       "Calendar dates + regular hours", "teal", "teal_edge")
p.card("entity_batch", 425, 255, 365, 100, "Ingest batch + source",
       "Request · feed · parser · as-of", "teal", "teal_edge")
p.card("entity_revision", 425, 400, 365, 100, "Daily bar revision",
       "Prices + volume · adjustment · status", "teal", "teal_edge")
p.card("entity_current", 425, 545, 365, 100, "Price used for calculations",
       "Original price, or a later provider correction", "teal", "teal_edge")
p.card("entity_request", 875, 280, 270, 100, "Analysis request",
       "Optional record · dates · snapshot · metric")
p.card("entity_result", 875, 445, 270, 100, "Result + evidence",
       "Derived on demand · coverage")
p.card("entity_turn", 875, 610, 270, 100, "Agent session + turn",
       "Later · plan · answer · evidence refs", "purple", "purple_edge")
p.card("entity_temporal_default", 1230, 315, 285, 115, "Temporal default",
       "Workflow events · timers · retries", "purple", "purple_edge", icon="database")
p.card("entity_temporal_visibility", 1230, 520, 285, 115, "Temporal visibility",
       "Workflow search + status", "purple", "purple_edge", icon="database")
p.edge("e_batch_revision", "entity_batch", "entity_revision", "provenance",
       color="teal_edge", exit_x=.5, exit_y=1, entry_x=.5, entry_y=0)
p.edge("e_revision_current", "entity_revision", "entity_current", "select",
       color="teal_edge", exit_x=.5, exit_y=1, entry_x=.5, entry_y=0)
p.edge("e_request_result", "entity_request", "entity_result", "calculate",
       exit_x=.5, exit_y=1, entry_x=.5, entry_y=0)
p.footer("05 / 07", "Accepted: one application PostgreSQL store for market facts   ·   Separate Temporal default + visibility databases")

# 06 — First deployment and operational boundaries.
p = Page("deployment", "06 · Deployment", "Homelab deployment view",
         "Physical placement proposal from the measured host; logical boundaries remain if deployment changes.")
p.card("device", 80, 350, 240, 130, "Creator devices",
       "Private access over Tailscale", "teal", "teal_edge", icon="monitor")
p.group("homelab", 385, 205, 1150, 550,
        "THELAB · UBUNTU 24.04 · 6 CORES / 12 THREADS · 15 GiB RAM",
        fill="gray")
p.group("runtime", 430, 275, 600, 370, "CONTAINER RUNTIME · PROPOSED", fill="white")
p.group("nvme", 1070, 275, 420, 220, "NVMe ROOT · 214 GB FREE", fill="white")
p.group("hdd", 1070, 525, 420, 180, "HDD · /srv/storage · 3.4 TB FREE", fill="white")
p.card("web_runtime", 465, 340, 240, 95, "Web + API",
       "Frontend location open · FastAPI", icon="server")
p.card("worker_runtime", 745, 340, 240, 95, "Workers",
       "Ingestion; separate agent worker later", icon="server")
p.card("temporal_runtime", 465, 500, 240, 95, "Temporal",
       "Service + UI", "purple", "purple_edge", icon="clock")
p.card("ops_runtime", 745, 500, 240, 95, "Operations",
       "Metrics · alerts", icon="server")
p.card("pg_nvme", 1105, 345, 345, 100, "PostgreSQL",
       "App DB + Temporal default/visibility DBs", "teal", "teal_edge", icon="database")
p.card("backups_hdd", 1105, 575, 345, 90, "Backup staging · later",
       "No backups in the first private deployment", "gray", "gray_edge", dashed=True)
p.card("offhost", 1080, 790, 400, 70, "Off-host backup · later",
       "Destination and restore checks undecided", "amber", "amber_edge", dashed=True,
       icon="cloud")
p.edge("dep_device", "device", "web_runtime", "Tailscale",
       color="teal_edge", exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("dep_api_pg", "web_runtime", "pg_nvme", "data",
       color="teal_edge", exit_x=.5, exit_y=0, entry_x=.5, entry_y=0,
       waypoints=[(585, 320), (1277, 320)])
p.edge("dep_worker_pg", "worker_runtime", "pg_nvme", "write",
       color="teal_edge", exit_x=1, exit_y=.5, entry_x=0, entry_y=.7)
p.edge("dep_temporal_pg", "temporal_runtime", "pg_nvme", "history",
       color="purple_edge", exit_x=.5, exit_y=1, entry_x=0, entry_y=.85,
       waypoints=[(585, 625), (1050, 625), (1050, 430)])
p.edge("dep_backup", "pg_nvme", "backups_hdd", "later backup",
       dashed=True, exit_x=.5, exit_y=1, entry_x=.5, entry_y=0)
p.edge("dep_offhost", "backups_hdd", "offhost", "future copy",
       color="amber_edge", dashed=True, exit_x=.5, exit_y=1, entry_x=.5, entry_y=0)
p.footer("06 / 07", "Initial private deployment: no backups   ·   Frontend placement and Docker / Kubernetes remain open")

# 07 — Temporal execution topology; workflow boxes are durable, activity boxes run I/O.
p = Page("workflow_topology", "07 · Workflows", "Temporal workflow topology",
         "One backfill workflow controls bounded batches; scheduled jobs are separate workflow executions.")
p.group("backfill_group", 55, 190, 1490, 280,
        "INITIAL BACKFILL · ONE WORKFLOW, FIVE STOCKS × FIVE YEARS PER ACTIVITY", fill="gray")
p.card("backfill_trigger", 80, 245, 230, 100, "Manual start",
       "Pinned catalog · 5-year window", "amber", "amber_edge", icon="person")
p.card("backfill_control", 375, 245, 310, 100, "Backfill workflow",
       "~100 groups + narrow repairs", "purple", "purple_edge", icon="clock")
p.card("backfill_activity", 750, 245, 355, 100, "Default group activity",
       "5 stocks × 5 years; fetch all pages", icon="server")
p.card("backfill_store", 1180, 245, 315, 100, "Application PostgreSQL",
       "Catalog + stored daily prices", "teal", "teal_edge", icon="database")
p.card("backfill_check", 750, 365, 355, 70, "Completeness activity",
       "SQL check · targeted stock/date repair", icon="server")
p.label("backfill_outcome", 1150, 365, 355, 70,
        "Workflow outcome: complete, incomplete, or failed. No gap table.", 16, "muted")
p.edge("wf_backfill_start", "backfill_trigger", "backfill_control",
       exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("wf_backfill_chunk", "backfill_control", "backfill_activity",
       color="purple_edge", exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("wf_backfill_write", "backfill_activity", "backfill_store", "write",
       color="teal_edge", exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.edge("wf_backfill_check", "backfill_activity", "backfill_check",
       exit_x=.5, exit_y=1, entry_x=.5, entry_y=0)
p.group("scheduled_group", 55, 500, 1490, 310,
        "OTHER RUNS · EACH ROW STARTS ITS OWN WORKFLOW EXECUTION", fill="gray")
p.card("refresh_trigger", 80, 545, 245, 70, "Hourly session tick",
       "Exchange-calendar gate", "amber", "amber_edge")
p.card("refresh_control", 380, 545, 315, 70, "Refresh workflow",
       "One run per tick", "purple", "purple_edge")
p.card("refresh_activity", 760, 545, 355, 70, "Fetch cumulative day bar",
       "Report freshness + count")
p.card("refresh_result", 1180, 545, 315, 70, "Provisional status",
       "Source as-of shown", "teal", "teal_edge")
p.card("final_trigger", 80, 635, 245, 70, "Next-day recheck",
       "No final-time assumption", "amber", "amber_edge")
p.card("final_control", 380, 635, 315, 70, "Reconcile workflow",
       "One run per session", "purple", "purple_edge")
p.card("final_activity", 760, 635, 355, 70, "Refetch + completeness",
       "Reuse backfill activities")
p.card("final_result", 1180, 635, 315, 70, "Latest accepted price",
       "Complete or incomplete", "teal", "teal_edge")
p.card("catalog_trigger", 80, 725, 245, 70, "Manual catalog run",
       "Later schedule open", "amber", "amber_edge")
p.card("catalog_control", 380, 725, 315, 70, "Catalog workflow",
       "One source snapshot", "purple", "purple_edge")
p.card("catalog_activity", 760, 725, 355, 70, "Fetch + review changes",
       "Publish atomically if accepted")
p.card("catalog_result", 1180, 725, 315, 70, "Published catalog",
       "Or held for review", "teal", "teal_edge")
for row in ("refresh", "final", "catalog"):
    p.edge(f"wf_{row}_start", f"{row}_trigger", f"{row}_control",
           exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
    p.edge(f"wf_{row}_activity", f"{row}_control", f"{row}_activity",
           color="purple_edge", exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
    p.edge(f"wf_{row}_result", f"{row}_activity", f"{row}_result",
           color="teal_edge", exit_x=1, exit_y=.5, entry_x=0, entry_y=.5)
p.footer("07 / 07", "Default 5-stock / 5-year activities accepted   ·   Specific failures use narrower repair activities")

ET.indent(file, space="  ")
ET.ElementTree(file).write(OUT, encoding="utf-8", xml_declaration=True)
print(f"Wrote {OUT}")
