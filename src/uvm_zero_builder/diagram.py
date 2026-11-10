"""Testbench block diagrams as SVG, drawn at fixed positions.

The layout is UVM style and always the same shape:

- the DUT sits in the centre, input interfaces on its left, output interfaces on its right;
- active agents (those that drive) sit above it, passive agents below;
- inside an agent box the stimulus, handler, and driver column sits beside the
  scoreboard and monitor column, drivers and monitors facing the DUT.

Every arrow is routed through the empty gaps between rows, boxes, and the DUT,
so nothing is drawn across a component. An interface counts as an input when a
driver drives it, otherwise as an output. The clock and reset agents are tried in
every position in both rows, and the arrangement with the fewest crossings wins.

audit() checks a layout without anyone having to look at it: no wire through a
component, no wires of different nets lying together, no overlapping boxes, every
net joined up and reaching each end with an arrow into each target. It also counts
crossings. render() draws the best arrangement; check() returns its audit.

``python -m uvm_zero_builder.diagram docs/architecture.svg`` writes the generic
architecture diagram the README shows.
"""

import itertools
import sys
from dataclasses import dataclass, field
from html import escape
from pathlib import Path


@dataclass
class Part:
    id: str
    label: str
    kind: str          # stimulus, handler, driver, monitor, or scoreboard


@dataclass
class Box:
    id: str
    label: str
    active: bool
    stimuli: list = field(default_factory=list)
    handler: Part = None
    drivers: list = field(default_factory=list)
    monitors: list = field(default_factory=list)
    scoreboards: list = field(default_factory=list)
    simple: bool = False   # the clock and reset agents: one labelled box

    def sections(self):
        """Rows per column, farthest from the DUT first."""
        drive = [row for row in (self.stimuli, [self.handler] if self.handler else [], self.drivers) if row]
        observe = [row for row in (self.scoreboards, self.monitors) if row]
        return [section for section in (drive, observe) if section]

    def parts(self):
        return [part for section in self.sections() for row in section for part in row]


@dataclass
class Diagram:
    title: str
    dut: str
    boxes: list
    interfaces: list       # (id, label, is_input)
    edges: list            # (source id, target id) between parts, interfaces, and "dut"


# ---------------------------------------------------------------- from a plan

_KINDS = ("stimulus", "driver", "monitor", "scoreboard")


def _part_id(kind, where, key):
    return f"{kind}:{where}:{key}"


def from_plan(plan):
    """The diagram of a checked plan."""
    boxes, edges, interfaces = [], [], []
    tests = plan.simulation["tests"]
    nodes = [node for top in plan.agents for node in top.walk()]
    for node in nodes:
        parts = {kind: [] for kind in _KINDS}
        for kind in _KINDS:
            if kind in ("driver", "stimulus") and not node.active:
                continue
            for key, value, _ in node.members(kind):
                label = value if isinstance(value, str) else kind.capitalize()
                parts[kind].append(Part(_part_id(kind, node.where, key), label, kind))
        handler = Part(f"handler:{node.where}", "Handler", "handler") if parts["driver"] else None
        if not any(parts.values()):
            continue
        boxes.append(Box(f"agent:{node.where}", f"{node.where} agent", bool(parts["driver"] or parts["stimulus"]),
                         parts["stimulus"], handler, parts["driver"], parts["monitor"], parts["scoreboard"]))

    shown = {part.id for box in boxes for part in box.parts()}
    driven = set()
    for node in nodes:
        drives = node.active and any(True for _ in node.members("driver"))
        for key, _, _ in node.members("stimulus"):
            stimulus = _part_id("stimulus", node.where, key)
            for _, child in node.subtree():
                if child.active and any(True for _ in child.members("driver")):
                    edges.append((stimulus, f"handler:{child.where}"))
            # A stimulus reads the interfaces' values, which the monitors keep current.
            for _, child in node.subtree():
                edges += [(_part_id("monitor", child.where, monitor), stimulus)
                          for monitor, _, _ in child.members("monitor")]
        for key, _, keys in node.members("driver"):
            if drives:
                edges.append((f"handler:{node.where}", _part_id("driver", node.where, key)))
                for interface in keys:
                    edges.append((_part_id("driver", node.where, key), f"if:{node.where}.{interface}"))
                    driven.add(f"if:{node.where}.{interface}")
        for key, _, keys in node.members("monitor"):
            edges += [(f"if:{node.where}.{interface}", _part_id("monitor", node.where, key)) for interface in keys]
        for route in node.routes():
            edges.append((_part_id(route.source_kind, route.source_node.where, route.source_key),
                          _part_id(route.target_kind, route.target_node.where, route.target_key)))

    # Label an interface by its name alone when unique, else by its path below the top-level agent.
    ids = [(f"if:{node.where}.{key}", node, key) for node in nodes for key in node.interfaces]
    leaves = [key for _, _, key in ids]
    single_top = len(plan.agents) == 1
    for name, node, key in ids:
        path = node.path[1:] if single_top else node.path
        label = key if leaves.count(key) == 1 else ".".join((*path, key))
        interfaces.append((name, f"{label} interface", name in driven))

    if plan.clock is not None:
        active = plan.clock.get("active", True)
        boxes.append(Box("clock", "Clock agent", active, simple=True))
        edges.append(("clock", "dut") if active else ("dut", "clock"))
    if plan.reset is not None:
        boxes.append(Box("reset", "Reset agent", True, simple=True))
        edges.append(("reset", "dut"))

    known = shown | {name for name, _, _ in interfaces} | {"dut", "clock", "reset"}
    edges = [edge for edge in dict.fromkeys(edges) if edge[0] in known and edge[1] in known]
    title = f"Test: {', '.join(tests) or 'none yet'}  ·  TbEnv"
    return Diagram(title, plan.simulation.get("toplevel") or "dut", boxes, interfaces, edges)


def architecture():
    """The generic diagram for the README: one active and one passive agent."""
    stimulus, handler = Part("st", "Stimulus", "stimulus"), Part("hd", "Handler", "handler")
    driver, monitor = Part("drv", "Driver", "driver"), Part("mon", "Monitor", "monitor")
    scoreboard = Part("sb", "Scoreboard", "scoreboard")
    out_monitor, out_scoreboard = Part("omon", "Monitor", "monitor"), Part("osb", "Scoreboard", "scoreboard")
    boxes = [Box("active", "Active agent", True, [stimulus], handler, [driver], [monitor], [scoreboard]),
             Box("passive", "Passive agent", False, monitors=[out_monitor], scoreboards=[out_scoreboard]),
             Box("clock", "Clock agent", True, simple=True), Box("reset", "Reset agent", True, simple=True)]
    edges = [("st", "hd"), ("hd", "drv"), ("drv", "if_in"), ("if_in", "mon"), ("mon", "sb"), ("mon", "st"),
             ("if_out", "omon"), ("omon", "osb"), ("clock", "dut"), ("reset", "dut")]
    interfaces = [("if_in", "Input interface", True), ("if_out", "Output interface", False)]
    return Diagram("Test  ·  TbEnv", "DUT", boxes, interfaces, edges)


# ---------------------------------------------------------------- layout
#
# Wires are drawn as schematic nets: each net has one horizontal bus on a track,
# vertical stems from the bus to each part, and a junction dot where a stem joins
# the bus part way along. Tracks live in channels, the empty strips between rows;
# each channel orders its tracks to cross as few stems as it can.

CHAR, NODE_H, NODE_GAP, PAD, TITLE_H, TRACK = 7.0, 30, 18, 16, 28, 12
SIMPLE_H, IF_H, IF_GAP, STEP, DUT_W, DUT_GAP, MARGIN, BOX_GAP, HEADER = 44, 32, 22, 48, 140, 60, 20, 40, 44
WIRE = "#546e7a"
FILL = {"stimulus": ("#ede7f6", "#7e57c2"), "handler": ("#eceff1", "#78909c"),
        "driver": ("#e3f2fd", "#1e88e5"), "monitor": ("#e8f5e9", "#43a047"),
        "scoreboard": ("#fff3e0", "#fb8c00"), "interface": ("#fffde7", "#b59a00")}


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float

    left = property(lambda self: self.x)
    right = property(lambda self: self.x + self.w)
    top = property(lambda self: self.y)
    bottom = property(lambda self: self.y + self.h)
    cx = property(lambda self: self.x + self.w / 2)
    cy = property(lambda self: self.y + self.h / 2)


def _width(label):
    return max(100, round(len(label) * CHAR + 28))


def _spread(low, high, index, count):
    return low + (high - low) * (index + 1) / (count + 1)


class Track:
    """One horizontal bus. Stems join it at (x, side): side -1 leaves upwards, +1 downwards."""

    def __init__(self, channel, net):
        self.channel, self.net, self.stems, self.y = channel, net, [], None

    def stem(self, x, side):
        self.stems.append((x, side))

    @property
    def span(self):
        xs = [x for x, _ in self.stems]
        return min(xs), max(xs)


class Channel:
    """A horizontal strip between y0 and y1 that holds parallel tracks."""

    def __init__(self, y0, y1):
        self.y0, self.y1, self.tracks = y0, y1, []

    def track(self, net):
        track = Track(self, net)
        self.tracks.append(track)
        return track

    @property
    def mid(self):
        return (self.y0 + self.y1) / 2

    def solve(self):
        tracks = self.tracks
        if not tracks:
            return

        def crossings(order):
            rank = {id(track): index for index, track in enumerate(order)}
            count = 0
            for track in order:
                for other in order:
                    if other is track:
                        continue
                    low, high = other.span
                    for x, side in track.stems:
                        if low < x < high and (rank[id(other)] - rank[id(track)]) * side > 0:
                            count += 1
            return count

        if len(tracks) <= 6:
            order = min(itertools.permutations(tracks), key=crossings)
        else:
            order = []
            for track in tracks:
                order = min((order[:i] + [track] + order[i:] for i in range(len(order) + 1)), key=crossings)
        for index, track in enumerate(order):
            track.y = _spread(self.y0, self.y1, index, len(order))


def _y(value):
    return value.y if isinstance(value, Track) else value


@dataclass
class Net:
    kind: str                     # inner-down, inner-up, inner, cross, interface, control
    key: tuple
    edges: list = field(default_factory=list)
    tracks: list = field(default_factory=list)
    lines: list = field(default_factory=list)      # (points, arrow); points may hold tracks as y
    trunks: list = field(default_factory=list)     # (x, [y values]): vertical joins between tracks


class _BoxGeometry:
    """An agent box in its own coordinates, drivers and monitors at the bottom."""

    def __init__(self, box, row_gap, lanes):
        self.box, self.row_gap, self.place, self.lane = box, row_gap, {}, None
        if box.simple:
            self.w, self.h, self.sections = max(120, _width(box.label)), SIMPLE_H, []
            return
        self.sections = box.sections()
        widths = [max(sum(_width(p.label) for p in row) + NODE_GAP * (len(row) - 1) for row in section)
                  for section in self.sections]
        heights = [len(section) * NODE_H + (len(section) - 1) * row_gap for section in self.sections]
        content = max(heights)
        x = PAD
        for index, (section, width, height) in enumerate(zip(self.sections, widths, heights)):
            for row_index, row in enumerate(section):
                top = TITLE_H + row_gap + (content - height) + row_index * (NODE_H + row_gap)
                left = x + (width - (sum(_width(p.label) for p in row) + NODE_GAP * (len(row) - 1))) / 2
                for position, part in enumerate(row):
                    self.place[part.id] = (Rect(left, top, _width(part.label), NODE_H), index, row_index,
                                           position, len(row))
                    left += _width(part.label) + NODE_GAP
            x += width
            if index == 0 and (len(self.sections) == 2 or lanes):
                room = max(48 if len(self.sections) == 2 else 0, 24 + TRACK * lanes)
                self.lane = (x, x + room)
                x += room
        self.w = max(x + PAD, _width(box.label) + 2 * PAD)
        self.h = TITLE_H + row_gap + content + PAD


class _Layout:
    """One complete layout for a given order of boxes in the top and bottom rows."""

    def __init__(self, diagram, rows=None):
        self.d = diagram
        self.owner = {part.id: box for box in diagram.boxes for part in box.parts()}
        self.box = {box.id: box for box in diagram.boxes}
        self.iface = {name: (label, is_input) for name, label, is_input in diagram.interfaces}
        rows = rows or _default_rows(diagram)
        self.top, self.bottom = list(rows["top"]), list(rows["bottom"])
        self.row_of = {box.id: name for name in ("top", "bottom") for box in rows[name]}
        self._nets()
        self._geometry()
        self._place()
        self._route()
        for channel in self.channels:
            channel.solve()

    # ------------------------------------------------------------ topology

    def _info(self, part):
        """(box, section, row, position in row, row length) from the box's own structure."""
        box = self.owner[part]
        for section_index, section in enumerate(box.sections()):
            for row_index, row in enumerate(section):
                for position, item in enumerate(row):
                    if item.id == part:
                        return box, section_index, row_index, position, len(row)
        raise KeyError(part)

    def _row(self, end):
        return self.row_of[self.box_of(end).id]

    def box_of(self, end):
        return self.box[end] if end in self.box else self.owner[end]

    def _side_entry(self, part):
        """True when a part can take a wire on its side from the box's lane."""
        box, section, _, position, length = self._info(part)
        sections = len(box.sections())
        return (section == 0 and position == length - 1) or (section == 1 and position == 0 and sections == 2)

    def _nets(self):
        nets = {}

        def net(kind, key):
            if (kind, key) not in nets:
                nets[(kind, key)] = Net(kind, key)
            return nets[(kind, key)]

        cross = []
        for a, b in self.d.edges:
            if a in self.owner and b in self.owner:
                if self.owner[a] is self.owner[b]:
                    _, section_a, row_a, _, _ = self._info(a)
                    _, section_b, row_b, _, _ = self._info(b)
                    if section_a == section_b and row_b == row_a + 1:
                        net("inner-down", a).edges.append((a, b))      # fan out from one source
                    elif section_a == section_b and row_b == row_a - 1:
                        net("inner-up", b).edges.append((a, b))        # fan in to one target
                    else:
                        net("inner", b).edges.append((a, b))
                else:
                    cross.append((a, b))
            elif a in self.iface or b in self.iface:
                name, end = (a, b) if a in self.iface else (b, a)
                net("interface", (name, self._row(end))).edges.append((a, b))
            else:
                end = a if b == "dut" else b
                net("control", end).edges.append((a, b))
        fan_in = {}
        for a, b in cross:
            fan_in[b] = fan_in.get(b, 0) + 1
        for a, b in cross:
            net("cross", ("from", a) if fan_in[b] == 1 else ("to", b)).edges.append((a, b))
        self.nets = list(nets.values())

        # Gap channels inside the boxes: (box, section, row) is the gap on the far side of that row.
        self.gap_use, self.lane_use, self.gutter_use = {}, {}, {}
        for item in self.nets:
            gaps = set()
            for a, b in item.edges:
                if item.kind == "inner-down":
                    box, section, row, _, _ = self._info(a)
                    gaps.add((box.id, section, row + 1))
                elif item.kind == "inner-up":
                    box, section, row, _, _ = self._info(a)
                    gaps.add((box.id, section, row))
                elif item.kind == "inner":
                    box, section, row, _, _ = self._info(a)
                    gaps.add((box.id, section, row))
                    if not self._side_entry(b):
                        _, section_b, row_b, _, _ = self._info(b)
                        gaps.add((box.id, section_b, row_b))
                    self.lane_use.setdefault(box.id, set()).add(item.key)
                elif item.kind == "cross":
                    for end in (a, b):
                        box, section, row, _, _ = self._info(end)
                        if row:
                            gaps.add((box.id, section, row, end))
                            side = "left" if section == 0 else "right"
                            self.gutter_use.setdefault((box.id, side), set()).add((item.key, end))
            for gap in gaps:
                self.gap_use.setdefault(gap[:3], set()).add((item.key, gap[3:]))

    # ------------------------------------------------------------ geometry

    def _geometry(self):
        self.geometry = {}
        for box in self.d.boxes:
            busiest = max([len(nets) for (box_id, _, _), nets in self.gap_use.items() if box_id == box.id] or [0])
            row_gap = max(44, (busiest + 1) * TRACK)
            self.geometry[box.id] = _BoxGeometry(box, row_gap, len(self.lane_use.get(box.id, ())))

    def _gutters(self, row):
        gaps = []
        for index in range(len(row) + 1):
            right = len(self.gutter_use.get((row[index - 1].id, "right"), ())) if index else 0
            left = len(self.gutter_use.get((row[index].id, "left"), ())) if index < len(row) else 0
            inner = BOX_GAP if 0 < index < len(row) else 0
            gaps.append(inner + (left + right) * TRACK + (12 if left + right else 0))
        return gaps

    def _stacks(self):
        """Per side: the interfaces, whether wires reach them from above, below, or both."""
        stacks = {}
        for side, is_input in (("left", True), ("right", False)):
            names = [name for name, _, flag in self.d.interfaces if flag == is_input]
            rows = {name: {item.key[1] for item in self.nets if item.kind == "interface" and item.key[0] == name}
                    for name in names}
            above = any("top" in r for r in rows.values())
            below = any("bottom" in r for r in rows.values())
            mode = "both" if above and below else "bottom" if below else "top" if above else "none"
            stacks[side] = {"names": names, "rows": rows, "mode": mode}
        return stacks

    def _place(self):
        stacks = self._stacks()
        widths = {}
        for side, stack in stacks.items():
            names = stack["names"]
            if_w = max([_width(self.iface[name][0]) for name in names] or [0])
            stack["if_w"] = if_w
            stagger = stack["mode"] in ("top", "bottom") and len(names) > 1
            stack["col_w"] = if_w + (len(names) - 1) * STEP if stagger else if_w
            trunks = 0
            if stack["mode"] == "both":
                trunks = sum("top" in stack["rows"][n] for n in names[1:]) + \
                    sum("bottom" in stack["rows"][n] for n in names[:-1])
            stack["trunks"] = trunks
            widths[side] = (DUT_GAP + stack["col_w"] + (16 + trunks * TRACK if trunks else 0)) if names else 0
        half = DUT_W / 2 + max(widths.values())
        rows = {"top": self.top, "bottom": self.bottom}
        row_width = {name: sum(self.geometry[b.id].w for b in row) + sum(self._gutters(row))
                     for name, row in rows.items()}
        self.mixed = [item for item in self.nets if item.kind == "cross"
                      and len({self._row(end) for edge in item.edges for end in edge}) == 2]
        reserve = (12 + TRACK * len(self.mixed)) if self.mixed else 0
        content = max(row_width["top"], row_width["bottom"], 2 * half)
        self.width = content + 2 * (MARGIN + reserve)
        center = self.width / 2

        # Rows of boxes, centred; the vertical positions follow once channel sizes are known.
        self.box_x = {}
        for name, row in rows.items():
            x = center - row_width[name] / 2
            for box, gap in zip(row, self._gutters(row)):
                x += gap
                self.box_x[box.id] = x
                x += self.geometry[box.id].w

        def count(kind, row):
            return sum(1 for item in self.nets if item.kind == kind and self._net_rows(item) & {row})

        y = HEADER
        bus_top = count("cross", "top")
        self.bus = {}
        if bus_top:
            self.bus["top"] = Channel(y, y + (bus_top + 1) * TRACK)
            y = self.bus["top"].y1
        top_h = max([self.geometry[b.id].h for b in self.top] or [0])
        self.row_y = {"top": (y, y + top_h)}
        y += top_h
        n = count("interface", "top") + count("control", "top")
        self.dut_channel = {"top": Channel(y + 6, y + max(56, (n + 1) * 15))}
        y = self.dut_channel["top"].y1 + 6 if self.top else y + 16

        stack_h = max([len(s["names"]) * IF_H + (len(s["names"]) - 1) * IF_GAP for s in stacks.values()] + [0])
        middle = max(stack_h + 24, 80)
        self.dut = Rect(center - DUT_W / 2, y, DUT_W, middle)
        y += middle

        n = count("interface", "bottom") + count("control", "bottom")
        if self.bottom:
            self.dut_channel["bottom"] = Channel(y + 6, y + max(56, (n + 1) * 15))
            y = self.dut_channel["bottom"].y1 + 6
        bottom_h = max([self.geometry[b.id].h for b in self.bottom] or [0])
        self.row_y["bottom"] = (y, y + bottom_h)
        y += bottom_h
        bus_bottom = count("cross", "bottom")
        if bus_bottom:
            self.bus["bottom"] = Channel(y, y + (bus_bottom + 1) * TRACK)
            y = self.bus["bottom"].y1
        self.height = y + MARGIN + 8

        # Boxes and parts at their final positions; passive boxes mirrored to face the DUT.
        self.box_rect, self.rect, self.gap = {}, {}, {}
        for name, row in rows.items():
            top, bottom = self.row_y[name]
            for box in row:
                geometry = self.geometry[box.id]
                below = name == "bottom"
                by = top if below else bottom - geometry.h
                bx = self.box_x[box.id]
                self.box_rect[box.id] = Rect(bx, by, geometry.w, geometry.h)

                def gy(local, geometry=geometry, by=by, below=below):
                    return by + (geometry.h - local if below else local)

                for part_id, (local, section, row_index, _, _) in geometry.place.items():
                    y0, y1 = sorted((gy(local.top), gy(local.bottom)))
                    self.rect[part_id] = Rect(bx + local.x, y0, local.w, local.h)
                    far = local.top
                    y0, y1 = sorted((gy(far - geometry.row_gap + 4), gy(far - 4)))
                    self.gap.setdefault((box.id, section, row_index), Channel(y0, y1))
        self.channels = list(self.gap.values()) + list(self.bus.values()) + list(self.dut_channel.values())

        # Interface stacks: staggered so every interface's wire side is open.
        self.stack = stacks
        self.if_attach = {}
        for side, stack in stacks.items():
            names = stack["names"]
            if not names:
                continue
            mode = stack["mode"]

            def mean_x(name):
                xs = [self.rect[end].cx for item in self.nets if item.kind == "interface" and item.key[0] == name
                      for edge in item.edges for end in edge if end in self.rect]
                return sum(xs) / len(xs) if xs else center

            descending = (side == "left") == (mode == "top")
            if mode == "both":
                names.sort(key=lambda n: (0 if stack["rows"][n] == {"top"} else 2 if stack["rows"][n] == {"bottom"}
                                          else 1, mean_x(n)))
            else:
                names.sort(key=mean_x, reverse=descending)
            height = len(names) * IF_H + (len(names) - 1) * IF_GAP
            top = self.dut.cy - height / 2
            if_w, n = stack["if_w"], len(names)
            for index, name in enumerate(names):
                depth = 0 if mode in ("both", "none") or n == 1 else index if mode == "top" else n - 1 - index
                if side == "left":
                    x = self.dut.left - DUT_GAP - if_w - depth * STEP
                else:
                    x = self.dut.right + DUT_GAP + depth * STEP
                rect = Rect(x, top + index * (IF_H + IF_GAP), if_w, IF_H)
                self.rect[name] = rect
                stagger_x = (rect.left + STEP / 2) if side == "left" else (rect.right - STEP / 2)
                for row in ("top", "bottom"):
                    edge_y = rect.top if row == "top" else rect.bottom
                    if mode == "both":
                        exposed = (row == "top" and index == 0) or (row == "bottom" and index == n - 1)
                    else:
                        exposed = mode == row
                    if exposed:
                        x_at = rect.cx if n == 1 or mode == "both" else stagger_x
                        self.if_attach[(name, row)] = ("edge", x_at, edge_y)
            # Side trunks when wires come from both directions.
            if mode == "both":
                order = [(n_, "top") for n_ in reversed(names[1:]) if "top" in stack["rows"][n_]] + \
                        [(n_, "bottom") for n_ in names[:-1] if "bottom" in stack["rows"][n_]]
                for k, (name, row) in enumerate(order):
                    rect = self.rect[name]
                    if side == "left":
                        x = rect.left - 16 - (len(order) - 1 - k) * TRACK
                        outer = rect.left
                    else:
                        x = rect.right + 16 + (len(order) - 1 - k) * TRACK
                        outer = rect.right
                    entry = rect.cy + (-7 if row == "top" else 7)
                    self.if_attach[(name, row)] = ("side", x, entry, outer)

    def dut_links(self):
        """(edge, points) for the arrow between each interface and the DUT."""
        links = []
        for name, _, is_input in self.d.interfaces:
            rect, dut = self.rect[name], self.dut
            if is_input:
                links.append(((name, "dut"), [(rect.right, rect.cy), (dut.left, rect.cy)]))
            else:
                links.append((("dut", name), [(dut.right, rect.cy), (rect.left, rect.cy)]))
        return links

    def end_rect(self, end):
        """The rectangle a wire ends on: a part, an interface, the DUT, or a clock or reset box."""
        if end == "dut":
            return self.dut
        return self.rect[end] if end in self.rect else self.box_rect[end]

    def _net_rows(self, item):
        rows = set()
        for edge in item.edges:
            for end in edge:
                if end in self.owner or end in self.box:
                    rows.add(self._row(end))
        return rows

    # ------------------------------------------------------------ routing

    def _far(self, part):
        rect = self.rect[part]
        return rect.top if self.row_of[self.owner[part].id] == "top" else rect.bottom

    def _near(self, part):
        rect = self.rect[part]
        return rect.bottom if self.row_of[self.owner[part].id] == "top" else rect.top

    def _ports(self):
        """Spread the wires on one edge of a part, ordered by where they head."""
        uses = {}
        for item in self.nets:
            ends = [end for edge in item.edges for end in edge]
            xs = [self.rect[e].cx if e in self.rect else self.box_rect[e].cx if e in self.box_rect else self.dut.cx
                  for e in ends]
            heading = sum(xs) / len(xs)
            for a, b in item.edges:
                for end, edge in self._port_edges(item, a, b):
                    uses.setdefault((end, edge), {})[id(item)] = heading
        self.port = {}
        for (end, edge), headings in uses.items():
            rect = self.rect[end]
            order = sorted(headings, key=headings.get)
            for index, key in enumerate(order):
                self.port[(end, edge, key)] = _spread(rect.left, rect.right, index, len(order))

    def _port_edges(self, item, a, b):
        if item.kind == "inner-down":
            return [(a, "near"), (b, "far")]
        if item.kind == "inner-up":
            return [(a, "far"), (b, "near")]
        if item.kind == "inner":
            return [(a, "far")] + ([] if self._side_entry(b) else [(b, "far")])
        if item.kind == "cross":
            return [(a, "far"), (b, "far")]
        if item.kind == "interface":
            return [(end, "near") for end in (a, b) if end in self.owner]
        return []    # clock and reset wires pick their own clear positions

    def _x(self, item, end, edge):
        return self.port[(end, edge, id(item))]

    def _stem(self, item, track, end, edge, arrow):
        x = self._x(item, end, edge)
        y = self._far(end) if edge == "far" else self._near(end)
        track.stem(x, -1 if y < track.channel.mid else 1)
        item.lines.append(([(x, track), (x, y)], arrow))

    def _route(self):
        self._ports()
        self.lane_x = {}
        for box_id, keys in self.lane_use.items():
            low, high = self.geometry[box_id].lane
            bx = self.box_x[box_id]
            for index, key in enumerate(sorted(keys)):
                self.lane_x[(box_id, key)] = bx + _spread(low, high, index, len(keys))
        self.gutter_x = {}
        for (box_id, side), uses in self.gutter_use.items():
            rect = self.box_rect[box_id]
            for index, use in enumerate(sorted(uses)):
                self.gutter_x[(box_id, use)] = rect.left - 12 - index * TRACK if side == "left" else \
                    rect.right + 12 + index * TRACK
        controls = [item for item in self.nets if item.kind == "control"]
        self.dut_port = {}
        for row in ("top", "bottom"):
            mine = [item for item in controls if self._net_rows(item) == {row}]
            for index, item in enumerate(mine):
                self.dut_port[id(item)] = _spread(self.dut.left, self.dut.right, index, len(mine))
        outer = {id(item): MARGIN + 6 + index * TRACK for index, item in enumerate(self.mixed)}

        for item in sorted(self.nets, key=lambda n: n.kind == "control"):
            getattr(self, "_route_" + item.kind.replace("-", "_"))(item, outer)

    def _route_inner_down(self, item, _):
        source = item.key
        box, section, row, _, _ = self._info(source)
        track = self.gap[(box.id, section, row + 1)].track(item)
        item.tracks.append(track)
        self._stem(item, track, source, "near", False)
        for _, target in item.edges:
            self._stem(item, track, target, "far", True)

    def _route_inner_up(self, item, _):
        target = item.key
        source = item.edges[0][0]
        box, section, row, _, _ = self._info(source)
        track = self.gap[(box.id, section, row)].track(item)
        item.tracks.append(track)
        for a, _ in item.edges:
            self._stem(item, track, a, "far", False)
        self._stem(item, track, target, "near", True)

    def _route_inner(self, item, _):
        target = item.key
        box = self.owner[target]
        lane = self.lane_x[(box.id, item.key)]
        pieces = {}
        for a, _ in item.edges:
            _, section, row, _, _ = self._info(a)
            channel = self.gap[(box.id, section, row)]
            if channel not in pieces:
                pieces[channel] = channel.track(item)
            self._stem(item, pieces[channel], a, "far", False)
        ys = []
        if self._side_entry(target):
            rect = self.rect[target]
            entry_x = rect.right if lane > rect.cx else rect.left
            item.lines.append(([(lane, rect.cy), (entry_x, rect.cy)], True))
            ys.append(rect.cy)
        else:
            _, section, row, _, _ = self._info(target)
            channel = self.gap[(box.id, section, row)]
            if channel not in pieces:
                pieces[channel] = channel.track(item)
            self._stem(item, pieces[channel], target, "far", True)
        item.tracks += pieces.values()
        mids = [channel.mid for channel in pieces] + ys
        if len(mids) > 1:
            for channel, track in pieces.items():
                for other in mids:
                    if other != channel.mid:
                        track.stem(lane, -1 if other < channel.mid else 1)
            item.trunks.append((lane, list(pieces.values()) + ys))

    def _route_cross(self, item, outer):
        targets = {b for _, b in item.edges}
        buses = {}
        for end in dict.fromkeys(end for edge in item.edges for end in edge):
            row = self._row(end)
            if row not in buses:
                buses[row] = self.bus[row].track(item)
            bus = buses[row]
            toward_row = 1 if row == "top" else -1
            box, section, row_index, _, _ = self._info(end)
            arrow = end in targets
            if row_index == 0:
                self._stem(item, bus, end, "far", arrow)
            else:
                gap = self.gap[(box.id, section, row_index)].track(item)
                item.tracks.append(gap)
                self._stem(item, gap, end, "far", arrow)
                gx = self.gutter_x[(box.id, (item.key, end))]
                gap.stem(gx, -toward_row)
                bus.stem(gx, toward_row)
                item.trunks.append((gx, [gap, bus]))
        item.tracks += buses.values()
        if len(buses) == 2:
            x = outer[id(item)]
            buses["top"].stem(x, 1)
            buses["bottom"].stem(x, -1)
            item.trunks.append((x, [buses["top"], buses["bottom"]]))

    def _route_interface(self, item, _):
        name, row = item.key
        track = self.dut_channel[row].track(item)
        item.tracks.append(track)
        into_interface = False
        for a, b in item.edges:
            end = b if a == name else a
            self._stem(item, track, end, "near", a == name)
            into_interface |= b == name
        attach = self.if_attach[(name, row)]
        toward = 1 if row == "top" else -1
        if attach[0] == "edge":
            _, x, edge_y = attach
            track.stem(x, toward)
            item.lines.append(([(x, track), (x, edge_y)], into_interface))
        else:
            _, x, entry, outer_x = attach
            track.stem(x, toward)
            item.lines.append(([(x, track), (x, entry), (outer_x, entry)], into_interface))

    def _route_control(self, item, _):
        (a, b), = item.edges
        name = a if a != "dut" else b
        row = self._row(name)
        track = self.dut_channel[row].track(item)
        item.tracks.append(track)
        rect = self.box_rect[name]
        box_y = rect.bottom if row == "top" else rect.top
        dut_y = self.dut.top if row == "top" else self.dut.bottom
        toward = 1 if row == "top" else -1
        taken = [x for other in track.channel.tracks for x, _ in other.stems]

        def clear(candidates):
            return max(candidates, key=lambda c: (min([abs(c - t) for t in taken] or [99]) >= 14, -abs(c - candidates[0])))

        box_x = clear([rect.cx + d for d in (0, -24, 24, -40, 40)])
        x = clear([self.dut_port[id(item)] + d for d in (0, -16, 16, -32, 32)])
        track.stem(box_x, -toward)
        track.stem(x, toward)
        item.lines.append(([(box_x, track), (box_x, box_y)], b == name))
        item.lines.append(([(x, track), (x, dut_y)], b == "dut"))


# ---------------------------------------------------------------- arrangements and audit
#
# The clock and reset agents may sit anywhere in either row; every arrangement is
# laid out and audited, and the cleanest wins. The audit is also what the tests
# and the generator check, so a messy or broken drawing is caught without anyone
# having to look at it.

MAX_ARRANGEMENTS = 240


def _default_rows(diagram):
    return {"top": [box for box in diagram.boxes if box.active],
            "bottom": [box for box in diagram.boxes if not box.active]}


def arrangements(diagram):
    """Every placement of the clock and reset boxes; agents keep their own order and row."""
    default = _default_rows(diagram)
    yield default
    agents = {name: [box for box in row if not box.simple] for name, row in default.items()}
    movable = [box for box in diagram.boxes if box.simple]
    count = 0

    def place(rows, remaining):
        if not remaining:
            yield rows
            return
        box, rest = remaining[0], remaining[1:]
        for name in ("top", "bottom"):
            for index in range(len(rows[name]) + 1):
                trial = {key: list(value) for key, value in rows.items()}
                trial[name].insert(index, box)
                yield from place(trial, rest)

    for rows in place(agents, movable):
        count += 1
        if count > MAX_ARRANGEMENTS:
            return
        yield rows


@dataclass
class Audit:
    """What is wrong with a layout (problems) and how tidy it is (the rest; lower is better)."""

    problems: list = field(default_factory=list)
    crossings: int = 0          # one wire crossing another
    intrusions: int = 0         # a wire running across an agent box it has nothing to do with
    length: float = 0.0         # total wire length

    @property
    def score(self):
        return (len(self.problems), self.crossings + 2 * self.intrusions, round(self.length))


def best_layout(diagram):
    """The arrangement with the fewest problems, then crossings, then wire."""
    best = None
    for rows in arrangements(diagram):
        layout = _Layout(diagram, rows)
        report = audit(layout)
        if best is None or report.score < best[1].score:
            best = (layout, report)
    return best


def _segments(layout):
    """Every straight piece of wire as (net index, x1, y1, x2, y2), ordered low to high."""
    pieces = []
    for index, item in enumerate(layout.nets):
        for track in item.tracks:
            low, high = track.span
            pieces.append((index, low, track.y, high, track.y))
        for x, ys in item.trunks:
            values = [_y(v) for v in ys]
            pieces.append((index, x, min(values), x, max(values)))
        for points, _ in item.lines:
            resolved = [(x, _y(y)) for x, y in points]
            for (x1, y1), (x2, y2) in zip(resolved, resolved[1:]):
                pieces.append((index, x1, y1, x2, y2))
    base = len(layout.nets)
    for offset, (_, points) in enumerate(layout.dut_links()):
        (x1, y1), (x2, y2) = points
        pieces.append((base + offset, x1, y1, x2, y2))
    result = []
    for net, x1, y1, x2, y2 in pieces:
        if abs(x1 - x2) < 0.01 and abs(y1 - y2) < 0.01:
            continue
        result.append((net, min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)))
    return result


def _inside(rect, x, y, margin=0.0):
    return rect.left + margin < x < rect.right - margin and rect.top + margin < y < rect.bottom - margin


def _on_border(rect, x, y, tolerance=0.6):
    near_x = rect.left - tolerance <= x <= rect.right + tolerance
    near_y = rect.top - tolerance <= y <= rect.bottom + tolerance
    return near_x and near_y and not _inside(rect, x, y, tolerance)


def _cuts(piece, rect, margin=1.0):
    """True when a straight piece of wire passes through the inside of a rectangle."""
    _, x1, y1, x2, y2 = piece
    if y1 == y2:
        return rect.top + margin < y1 < rect.bottom - margin and x1 < rect.right - margin and x2 > rect.left + margin
    return rect.left + margin < x1 < rect.right - margin and y1 < rect.bottom - margin and y2 > rect.top + margin


def audit(layout, spacing=5.0):
    """Check a layout and measure how tidy it is.

    Problems: a slanted wire; components or boxes overlapping; a wire through a
    component, interface, the DUT, or a clock or reset box; wires of different nets
    lying on or right beside each other; a net whose wires do not join up, miss one
    of its ends, or lack the arrowhead on a target.
    """
    report = Audit()
    pieces = _segments(layout)
    for piece in pieces:
        if piece[1] != piece[3] and piece[2] != piece[4]:
            report.problems.append(f"slanted wire {piece[1:]}")
        report.length += (piece[3] - piece[1]) + (piece[4] - piece[2])

    # Solid things: wires must go around them and they must not overlap.
    solid = {name: layout.rect[name] for name in layout.rect}
    solid["dut"] = layout.dut
    solid.update({box.id: layout.box_rect[box.id] for box in layout.d.boxes if box.simple})
    names = list(solid)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ra, rb = solid[a], solid[b]
            if ra.left < rb.right and rb.left < ra.right and ra.top < rb.bottom and rb.top < ra.bottom:
                report.problems.append(f"{a} overlaps {b}")
    boxes = [box for box in layout.d.boxes if not box.simple]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            ra, rb = layout.box_rect[a.id], layout.box_rect[b.id]
            if ra.left < rb.right and rb.left < ra.right and ra.top < rb.bottom and rb.top < ra.bottom:
                report.problems.append(f"{a.id} overlaps {b.id}")
    for piece in pieces:
        for name, rect in solid.items():
            if _cuts(piece, rect):
                report.problems.append(f"wire {piece[1:]} runs through {name}")

    # Wires of different nets: crossing is allowed but counted; touching is not.
    for i, a in enumerate(pieces):
        for b in pieces[i + 1:]:
            if a[0] == b[0]:
                continue
            a_flat, b_flat = a[2] == a[4], b[2] == b[4]
            if a_flat == b_flat:
                if a_flat and abs(a[2] - b[2]) < spacing and min(a[3], b[3]) - max(a[1], b[1]) > 0.5:
                    report.problems.append(f"wires {a[1:]} and {b[1:]} run together")
                if not a_flat and abs(a[1] - b[1]) < spacing and min(a[4], b[4]) - max(a[2], b[2]) > 0.5:
                    report.problems.append(f"wires {a[1:]} and {b[1:]} run together")
                continue
            flat, tall = (a, b) if a_flat else (b, a)
            if flat[1] + 0.5 < tall[1] < flat[3] - 0.5 and tall[2] + 0.5 < flat[2] < tall[4] - 0.5:
                report.crossings += 1

    # A wire across an agent box that none of its ends belongs to.
    for index, item in enumerate(layout.nets):
        mine = {layout.box_of(end).id for edge in item.edges for end in edge if end in layout.owner or end in layout.box}
        for box in boxes:
            if box.id in mine:
                continue
            if any(_cuts(piece, layout.box_rect[box.id], 0) for piece in pieces if piece[0] == index):
                report.intrusions += 1

    # Every net joins up, touches each of its ends, and points at each target.
    for index, item in enumerate(layout.nets):
        own = [piece for piece in pieces if piece[0] == index]
        if not own:
            report.problems.append(f"net {item.key} has no wires")
            continue
        group = list(range(len(own)))

        def root(k):
            while group[k] != k:
                group[k] = group[group[k]]
                k = group[k]
            return k

        def touches(p, q):
            ends = ((p[1], p[2]), (p[3], p[4]))
            return any(q[1] - 0.6 <= x <= q[3] + 0.6 and q[2] - 0.6 <= y <= q[4] + 0.6 for x, y in ends)

        for i, p in enumerate(own):
            for j in range(i + 1, len(own)):
                if touches(p, own[j]) or touches(own[j], p):
                    group[root(i)] = root(j)
        if len({root(k) for k in range(len(own))}) > 1:
            report.problems.append(f"net {item.key} is in pieces")
        for end in {end for edge in item.edges for end in edge}:
            rect = layout.end_rect(end)
            if not any(_on_border(rect, x, y) for p in own for x, y in ((p[1], p[2]), (p[3], p[4]))):
                report.problems.append(f"net {item.key} does not reach {end}")
        tips = [points[-1] for points, arrow in item.lines if arrow]
        for _, target in item.edges:
            rect = layout.end_rect(target)
            if not any(_on_border(rect, x, _y(y)) for x, y in tips):
                report.problems.append(f"net {item.key} has no arrow into {target}")
    return report


def check(diagram):
    """The audit of the arrangement render() draws."""
    return best_layout(diagram)[1]


# ---------------------------------------------------------------- drawing

def _text(x, y, label, size=12, weight="normal", fill="#212121", anchor="middle", halo=None):
    extra = f' stroke="{halo}" stroke-width="5" paint-order="stroke"' if halo else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}" dominant-baseline="central"{extra}>{escape(label)}</text>')


def _points(points):
    return " ".join(f"{x:.1f},{_y(y):.1f}" for x, y in points)


def _net_svg(item):
    out = [f'<g data-edges="{escape("|".join(f"{a} -> {b}" for a, b in item.edges))}">']
    plain = []
    for track in item.tracks:
        low, high = track.span
        if high > low:
            plain.append(f"M{low:.1f},{track.y:.1f} H{high:.1f}")
    for x, ys in item.trunks:
        values = [_y(v) for v in ys]
        plain.append(f"M{x:.1f},{min(values):.1f} V{max(values):.1f}")
    for points, arrow in item.lines:
        if not arrow:
            plain.append("M" + " L".join(f"{x:.1f},{_y(y):.1f}" for x, y in points))
    if plain:
        out.append(f'<path d="{" ".join(plain)}" fill="none" stroke="{WIRE}" stroke-width="1.5" '
                   'stroke-linejoin="round" stroke-linecap="round"/>')
    for points, arrow in item.lines:
        if arrow:
            out.append(f'<polyline points="{_points(points)}" fill="none" stroke="{WIRE}" stroke-width="1.5" '
                       'stroke-linejoin="round" marker-end="url(#arrow)"/>')
    # Junction dots where a stem meets a bus part way along, or a trunk passes through it.
    for track in item.tracks:
        low, high = track.span
        sides = {}
        for x, side in track.stems:
            sides.setdefault(round(x, 1), set()).add(side)
        for x, seen in sides.items():
            if len(seen) + (x > low + 0.1) + (x < high - 0.1) >= 3:
                out.append(f'<circle cx="{x:.1f}" cy="{track.y:.1f}" r="3" fill="{WIRE}"/>')
    out.append("</g>")
    return out


def render(diagram):
    """The SVG text of a diagram, laid out in its cleanest arrangement."""
    return draw(diagram)[0]


def draw(diagram):
    """(SVG text, Audit) for the cleanest arrangement of a diagram."""
    layout, report = best_layout(diagram)
    return _svg(diagram, layout), report


def _svg(diagram, layout):
    width, height = layout.width, layout.height
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
           f'viewBox="0 0 {width:.0f} {height:.0f}" font-family="Helvetica, Arial, sans-serif">',
           '<defs><marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" markerHeight="8" '
           f'markerUnits="userSpaceOnUse" orient="auto"><path d="M0,1 L10,5 L0,9 z" fill="{WIRE}"/></marker></defs>',
           f'<rect width="{width:.0f}" height="{height:.0f}" fill="#ffffff"/>',
           f'<rect x="6" y="6" width="{width - 12:.0f}" height="{height - 12:.0f}" rx="10" '
           'fill="none" stroke="#9e9e9e" stroke-dasharray="6 4"/>',
           _text(20, 25, diagram.title, 14, "bold", anchor="start")]
    if any(not box.simple for box in layout.top):
        out.append(_text(width - 20, 25, "Active agents ▼", 11, fill="#757575", anchor="end"))
    if any(not box.simple for box in layout.bottom):
        out.append(_text(width - 20, height - 20, "Passive agents ▲", 11, fill="#757575", anchor="end"))

    for box in diagram.boxes:
        rect = layout.box_rect[box.id]
        fill = "#f5f5f5" if box.simple else "#fafafa"
        out.append(f'<rect data-id="{escape(box.id)}" x="{rect.x:.1f}" y="{rect.y:.1f}" width="{rect.w:.1f}" '
                   f'height="{rect.h:.1f}" rx="8" fill="{fill}" stroke="#9e9e9e"/>')

    for item in layout.nets:
        out += _net_svg(item)
    for edge, points in layout.dut_links():
        out.append(f'<g data-edges="{escape(edge[0])} -> {escape(edge[1])}"><polyline points="{_points(points)}" '
                   f'fill="none" stroke="{WIRE}" stroke-width="1.5" marker-end="url(#arrow)"/></g>')

    for box in diagram.boxes:
        rect = layout.box_rect[box.id]
        if box.simple:
            out.append(_text(rect.cx, rect.cy, box.label, 12, "bold"))
        else:
            title_y = rect.y + TITLE_H / 2 + 2 if layout.row_of[box.id] == "top" else rect.bottom - TITLE_H / 2 - 2
            out.append(_text(rect.x + 12, title_y, box.label, 12, "bold", anchor="start", halo="#fafafa"))
        for part in box.parts():
            rect = layout.rect[part.id]
            fill, stroke = FILL[part.kind]
            out.append(f'<rect data-id="{escape(part.id)}" data-kind="{part.kind}" x="{rect.x:.1f}" '
                       f'y="{rect.y:.1f}" width="{rect.w:.1f}" height="{rect.h:.1f}" rx="5" fill="{fill}" '
                       f'stroke="{stroke}"/>')
            out.append(_text(rect.cx, rect.cy, part.label))
    for name, label, is_input in diagram.interfaces:
        rect = layout.rect[name]
        fill, stroke = FILL["interface"]
        kind = "input" if is_input else "output"
        out.append(f'<rect data-id="{escape(name)}" data-kind="{kind}" x="{rect.x:.1f}" y="{rect.y:.1f}" '
                   f'width="{rect.w:.1f}" height="{rect.h:.1f}" rx="5" fill="{fill}" stroke="{stroke}"/>')
        out.append(_text(rect.cx, rect.cy, label))
    dut = layout.dut
    out.append(f'<rect data-id="dut" x="{dut.x:.1f}" y="{dut.y:.1f}" width="{dut.w:.1f}" height="{dut.h:.1f}" '
               'rx="8" fill="#37474f" stroke="#263238"/>')
    named = diagram.dut != "DUT"
    out.append(_text(dut.cx, dut.cy - (8 if named else 0), "DUT", 14, "bold", "#ffffff"))
    if named:
        out.append(_text(dut.cx, dut.cy + 10, diagram.dut, 11, fill="#eceff1"))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    target = Path(argv[0] if argv else "docs/architecture.svg")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(architecture()), encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
