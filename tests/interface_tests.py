"""Self-tests: Interfaces and their JSON definitions."""
import cocotb

from support import *  # noqa: F401,F403  shared helpers and fixtures


@cocotb.test()
async def json_renames_signals(dut):
    interface = Interface.from_json(dut, write_json(
        {"signals": [".s_valid_i -> valid", ".s_data_i -> data", ".clk"]}))
    assert interface.valid._path == dut.s_valid_i._path
    assert interface.data._path == dut.s_data_i._path
    assert interface.clk._path == dut.clk._path
    assert not hasattr(interface, "s_valid_i")


@cocotb.test()
async def json_rename_resolves_name_collisions(dut):
    interface = Interface.from_json(dut, write_json(
        {"signals": [".a.valid -> a_valid", ".b.valid -> b_valid"]}))
    assert interface.a_valid._path == dut.a.valid._path
    assert interface.b_valid._path == dut.b.valid._path


@cocotb.test()
async def json_rename_works_with_extra_signals(dut):
    base = write_json({"signals": [".s_data_i -> mode"]})
    interface = Interface.from_json(dut, write_json({
        "interface": base,
        "extra_signals": [".s_valid_i -> valid"],
    }))
    assert interface.mode._path == dut.s_data_i._path
    assert interface.valid._path == dut.s_valid_i._path


@cocotb.test()
async def json_rename_syntax_is_strict(dut):
    for entry in (".clk->x", ".clk  -> x", ".clk -> ", ".clk -> 1x", " -> x", ".clk -> x y",
                  ".clk -> a -> b", ".clk x"):
        try:
            Interface.from_json(dut, write_json({"signals": [entry]}))
        except ValueError:
            continue
        raise AssertionError(f"accepted malformed entry {entry!r}")


@cocotb.test()
async def json_rejects_duplicate_names_after_renaming(dut):
    try:
        Interface.from_json(dut, write_json({"signals": [".clk -> x", ".rst_n -> x"]}))
    except ValueError as error:
        assert "duplicate" in str(error)
        return
    raise AssertionError("accepted duplicate names")


@cocotb.test()
async def json_accepts_a_bare_signal_list(dut):
    assert Interface.from_json(dut, write_json([".clk"])).clk._path == dut.clk._path


@cocotb.test()
async def json_top_level_module_overrides_an_absolute_lower_one(dut):
    lower = write_json({"signals": [".valid"], "connected_module": "dut.b"})
    top = write_json({"interface": lower, "connected_module": "dut.a"})
    assert Interface.from_json(dut, top).valid._path == dut.a.valid._path


@cocotb.test()
async def json_lower_relative_module_extends_the_upper_one(dut):
    lower = write_json({"signals": [".valid"], "connected_module": ".a"})
    top = write_json({"interface": lower, "connected_module": "dut"})
    assert Interface.from_json(dut, top).valid._path == dut.a.valid._path


@cocotb.test()
async def json_rooted_path_ignores_the_connected_module(dut):
    path = write_json({"signals": ["dut.a.valid"], "connected_module": "dut.b"})
    assert Interface.from_json(dut, path).valid._path == dut.a.valid._path


@cocotb.test()
async def json_bundle_selects_roles(dut):
    lower = write_json({"signals": [".valid"]})
    top = write_json({"connected_module": "dut.a", "interfaces": {
        "by_name": lower,
        "absolute": {"interface": lower, "connected_module": "dut.b"},
        "inline": {"signals": [".valid"]},
    }})
    assert Interface.from_json(dut, top, interface="by_name").valid._path == dut.a.valid._path
    assert Interface.from_json(dut, top, interface="absolute").valid._path == dut.b.valid._path
    assert Interface.from_json(dut, top, interface="inline").valid._path == dut.a.valid._path


@cocotb.test()
async def json_bundle_relative_entry_extends_the_bundle(dut):
    lower = write_json({"signals": [".u.valid"]})
    top = write_json({"connected_module": "dut", "interfaces": {
        "role": {"interface": lower, "connected_module": ".gen_blk[1]"}}})
    interface = Interface.from_json(dut, top, interface="role")
    assert interface.valid._path == dut.gen_blk[1].u.valid._path


@cocotb.test()
async def json_reference_passes_the_role_to_a_lower_bundle(dut):
    bundle = write_json({"connected_module": "dut.a", "interfaces": {"role": {"signals": [".valid"]}}})
    top = write_json({"interface": bundle})
    assert Interface.from_json(dut, top, interface="role").valid._path == dut.a.valid._path


@cocotb.test()
async def json_errors_are_reported(dut):
    expect_json_error(dut, {"signals": [".clk"], "typo": 1}, "exactly one")
    expect_json_error(dut, {"signals": [".clk"], "interface": "x.json"}, "exactly one")
    expect_json_error(dut, {}, "exactly one")
    expect_json_error(dut, {"signals": [".missing"]}, "not found")
    expect_json_error(dut, {"signals": [".clk"], "extra_signals": [".rst_n"]}, "extra_signals")
    expect_json_error(dut, {"signals": [".clk"]}, "no named interfaces", interface="role")
    expect_json_error(dut, {"interfaces": {"a": {"signals": [".clk"]}}}, "named interface", interface="b")
    expect_json_error(dut, {"interfaces": {"a": {"signals": [".clk"]}}}, "named interface")
    expect_json_error(dut, [".clk x"], "Invalid")


@cocotb.test()
async def json_circular_references_are_rejected(dut):
    first = write_json({})
    second = write_json({"interface": first})
    with open(first, "w", encoding="utf-8") as file:
        json.dump({"interface": second}, file)
    expect_json_error(dut, first, "Circular")


@cocotb.test()
async def json_invalid_syntax_is_reported(dut):
    handle, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(handle, "w", encoding="utf-8") as file:
        file.write("{not json")
    expect_json_error(dut, path, "invalid JSON")


@cocotb.test()
async def interface_paths_can_be_indexed(dut):
    interface = Interface.from_json(dut, write_json({"signals": [".gen_blk[1].u.valid -> valid"]}))
    assert interface.valid._path == dut.gen_blk[1].u.valid._path


@cocotb.test()
async def json_parameters_are_constants_read_from_the_dut(dut):
    lower = write_json({"signals": [".clk"], "parameters": [".WIDTH"]})
    path = write_json({"interface": lower, "parameters": [".DEPTH -> depth"]})
    interface = Interface.from_json(dut, path)
    assert interface.WIDTH == 8 and interface.depth == 3
    assert interface.parameters == {"WIDTH": 8, "depth": 3} and list(interface.signals) == ["clk"]
    child = Interface.from_json(dut, write_json({"connected_module": "dut.b", "signals": [".valid"],
                                                 "parameters": [".ID -> id"]}))
    assert child.id == 2
    # Observed values cover signals only: parameters are never sampled.
    child._sample()
    assert list(child.values) == ["valid"] and child.values.valid == child.values["valid"]


@cocotb.test()
async def parameters_and_signals_are_not_interchangeable(dut):
    for body, expected in (({"signals": [".clk", ".WIDTH"]}, "is a parameter, not a signal; list it under parameters"),
                           ({"signals": [".clk"], "parameters": [".clk"]}, "duplicate signal name 'clk'"),
                           ({"signals": [], "parameters": [".rst_n"]}, "is a signal, not a parameter"),
                           ({"signals": [], "parameters": ".WIDTH"}, "parameters must be a list")):
        try:
            Interface.from_json(dut, write_json(body))
        except ValueError as error:
            assert expected in str(error), (body, error)
        else:
            raise AssertionError(f"{body} was accepted")


@cocotb.test()
async def clocks_and_resets_are_tagged_in_the_json(dut):
    interface = Interface.from_json(dut, write_json(
        {"signals": [".clk [Clock]", ".rst_n -> reset [Reset]", ".s_valid_i -> valid", ".gen_blk[0].u.valid -> inner"]}))
    assert list(interface.clocks) == ["clk"] and list(interface.resets) == ["reset"]
    assert interface.clocks["clk"] is interface.clk
    # Clocks are not tracked in the observed values; resets and protocol signals are.
    interface._sample()
    assert sorted(interface.values) == ["inner", "reset", "valid"]
    for body, expected in (({"signals": [".clk [Clk]"]}, "Invalid signal entry"),
                           ({"signals": [".clk"], "parameters": [".WIDTH [Clock]"]}, "only signals take a [Clock] tag")):
        try:
            Interface.from_json(dut, write_json(body))
        except ValueError as error:
            assert expected in str(error), (body, error)
        else:
            raise AssertionError(f"{body} was accepted")


@cocotb.test()
async def generated_names_must_be_python_names(dut):
    try:
        Interface.from_json(dut, write_json({"signals": [".gen_blk[0]"]}))
    except ValueError as error:
        assert "'gen_blk[0]', which is not a Python name; rename it with '-> name'" in str(error), error
    else:
        raise AssertionError("an indexed name was accepted")


@cocotb.test()
async def inline_definitions_keep_the_selected_role(dut):
    bundle = write_json({"interface": {"interfaces": {"rx": {"signals": [".clk"]}}}})
    assert list(Interface.from_json(dut, bundle, interface="rx").signals) == ["clk"]
    plain = write_json({"interface": {"signals": [".clk"]}})
    try:
        Interface.from_json(dut, plain, interface="rx")
    except ValueError as error:
        assert "no named interfaces to select" in str(error)
    else:
        raise AssertionError("a role was accepted for a definition without roles")

