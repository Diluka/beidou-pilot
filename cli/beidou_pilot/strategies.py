"""读取 Lua 策略注释，并为原生入口准备已校验的调用参数。"""

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Literal

from .errors import ClientError, JsonObject, JsonValue


OptionType = Literal["int", "number", "string", "boolean"]
TickGear = Literal[1, 2, 3, 4]
_TICK_GEARS: dict[str, TickGear] = {"1": 1, "2": 2, "3": 3, "4": 4}
_ENTRY = re.compile(
    r"^\s*(?:(?:local\s+)?function\s+main\s*\(\s*context\s*\)|"
    r"(?:local\s+)?main\s*=\s*function\s*\(\s*context\s*\))\s*(?:--.*)?$"
)
_LONG_COMMENT = re.compile(r"--\[(=*)\[")
_OPTION_MARKER = re.compile(r"^\s*--+\s*@option(?:\b|\[)")
_OPTION = re.compile(r"^\s*--+\s*@option\[([^\]]+)\]\s+([A-Za-z_][A-Za-z0-9_]*)\s+(.+?)\s*$")
_RESERVED_FLAGS = {
    "--json",
    "--root",
    "--debug",
    "--backend",
    "--instance",
    "--version",
    "--help",
    "--session",
    "--library",
    "--code",
    "--seconds",
    "--continuous",
}


@dataclass(frozen=True)
class StrategyOption:
    name: str
    type: OptionType
    description: str
    optional: bool
    default: JsonValue
    has_default: bool
    minimum: int | float | None
    maximum: int | float | None
    choices: tuple[JsonValue, ...] | None

    @property
    def flag(self) -> str:
        return "--" + self.name.replace("_", "-")


@dataclass(frozen=True)
class ScriptExecution:
    mode: Literal["coroutine", "tick"] = "coroutine"
    budget_ms: float = 100
    overrun: Literal["abort", "skip"] = "abort"
    abort_commit: bool = True
    gear: TickGear = 3


@dataclass(frozen=True)
class StrategyMetadata:
    options: tuple[StrategyOption, ...]
    execution: ScriptExecution = ScriptExecution()

    @property
    def mode(self) -> Literal["coroutine", "tick"]:
        return self.execution.mode


def _script_header(source: str) -> tuple[int, list[tuple[int, str]]]:
    """扫描真实 Lua 前导注释，长注释内部文本不作为运行元数据。"""
    index, line_number = 0, 1
    comments: list[tuple[int, str]] = []
    while index < len(source):
        if source[index].isspace():
            line_number += source[index] == "\n"
            index += 1
            continue
        if not source.startswith("--", index):
            break
        block = _LONG_COMMENT.match(source, index)
        if block is not None:
            close = source.find("]" + block[1] + "]", block.end())
            end = len(source) if close < 0 else close + len(block[1]) + 2
        else:
            end = source.find("\n", index)
            end = len(source) if end < 0 else end + 1
            comments.append((line_number, source[index:end].rstrip("\r\n")))
        line_number += source[index:end].count("\n")
        index = end
    return index, comments


def split_script_header(source: str) -> tuple[str, str]:
    """保留前导注释，避免源码注入遮挡原生 mode 分派。"""
    index, _ = _script_header(source)
    return source[:index], source[index:]


def parse_script_execution(source: str) -> ScriptExecution:
    """文件和直接源码共用的前导 @mode/@tick 配置边界。"""
    _, comments = _script_header(source)
    declared: dict[str, str] = {}
    for line_number, line in comments:
        if not re.match(r"^\s*--+\s*@(mode\b|tick(?:\b|\.))", line):
            continue
        match = re.fullmatch(r"\s*--+\s*@(mode|tick\.[A-Za-z_]+)\s+(.+?)\s*", line)
        if match is None:
            raise _invalid_metadata("@mode/@tick 配置须为前导注释中的单个声明值。", line_number)
        key, raw_value = match.groups()
        value = raw_value.partition("--")[0].strip()
        if key not in {"mode", "tick.gear", "tick.budget_ms", "tick.overrun", "tick.abort_commit"} or key in declared:
            raise _invalid_metadata(f"脚本运行配置未知或重复：@{key}。", line_number)
        declared[key] = value
    mode = declared.get("mode", "coroutine")
    if mode not in {"coroutine", "tick"}:
        raise _invalid_metadata("@mode 只接受 coroutine 或 tick。")
    if mode != "tick" and any(key.startswith("tick.") for key in declared):
        raise _invalid_metadata("@tick 配置仅适用于显式声明 @mode tick 的脚本。")
    budget = declared.get("tick.budget_ms", "100")
    if not re.fullmatch(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", budget):
        raise _invalid_metadata("@tick.budget_ms 须为正有限十进制数。")
    budget_ms = float(budget)
    if not math.isfinite(budget_ms) or budget_ms <= 0:
        raise _invalid_metadata("@tick.budget_ms 须为正有限十进制数。")
    overrun = declared.get("tick.overrun", "abort")
    abort_commit = declared.get("tick.abort_commit", "true")
    if overrun not in {"abort", "skip"}:
        raise _invalid_metadata("@tick.overrun 只接受 abort 或 skip。")
    if abort_commit not in {"true", "false"}:
        raise _invalid_metadata("@tick.abort_commit 只接受 true 或 false。")
    gear = declared.get("tick.gear", "3")
    if gear not in _TICK_GEARS:
        raise _invalid_metadata("@tick.gear 只接受 1、2、3 或 4。")
    return ScriptExecution(mode, budget_ms, overrun, abort_commit == "true", _TICK_GEARS[gear])


def _invalid_metadata(message: str, line: int | None = None) -> ClientError:
    details = {"line": line} if line is not None else None
    return ClientError("invalid_strategy_metadata", message, details)


def _split_attributes(raw: str, line: int) -> list[str]:
    values: list[str] = []
    current: list[str] = []
    quoted = escaped = False
    for character in raw:
        if character == '"' and not escaped:
            quoted = not quoted
        if character == "," and not quoted:
            values.append("".join(current).strip())
            current = []
        else:
            current.append(character)
        escaped = character == "\\" and not escaped
        if character != "\\":
            escaped = False
    if quoted:
        raise _invalid_metadata("@option 属性中的引号没有闭合。", line)
    values.append("".join(current).strip())
    return values


def _value(raw: str, kind: OptionType, line: int) -> JsonValue:
    token = raw.strip()
    try:
        if kind == "string":
            return json.loads(token) if token.startswith('"') else token
        if kind == "int" and re.fullmatch(r"[+-]?\d+", token):
            return int(token)
        if kind == "number":
            number = float(token)
            if math.isfinite(number):
                return number
        if kind == "boolean" and token.lower() in {"true", "false"}:
            return token.lower() == "true"
    except (json.JSONDecodeError, ValueError):
        pass
    raise _invalid_metadata(f"@option 值 {raw!r} 不符合声明类型 {kind}。", line)


def _parse_option(attributes: str, name: str, description: str, line: int) -> StrategyOption:
    values: dict[str, str] = {}
    optional = False
    for part in _split_attributes(attributes, line):
        if part == "opt":
            if optional:
                raise _invalid_metadata("@option 的 opt 标记重复。", line)
            optional = True
            continue
        key, separator, value = part.partition("=")
        if not separator or key not in {"type", "default", "min", "max", "choices"} or key in values:
            raise _invalid_metadata(f"@option 属性无效或重复：{part!r}。", line)
        values[key] = value.strip()

    raw_type = values.get("type")
    if raw_type not in {"int", "number", "string", "boolean"}:
        raise _invalid_metadata("@option 必须指定 type=int、number、string 或 boolean。", line)
    kind = raw_type
    minimum = _value(values["min"], kind, line) if "min" in values and kind in {"int", "number"} else None
    maximum = _value(values["max"], kind, line) if "max" in values and kind in {"int", "number"} else None
    if ("min" in values or "max" in values) and kind not in {"int", "number"}:
        raise _invalid_metadata("min/max 只适用于 int 或 number 参数。", line)
    if minimum is not None and maximum is not None and minimum > maximum:
        raise _invalid_metadata("@option 的 min 不能大于 max。", line)

    choices = None
    if "choices" in values:
        choices = tuple(_value(choice, kind, line) for choice in values["choices"].split("|"))
        if not choices or any(choice == "" for choice in choices):
            raise _invalid_metadata("@option choices 必须包含非空的 | 分隔值。", line)
    has_default = "default" in values or kind == "boolean"
    if "default" in values:
        default = _value(values["default"], kind, line)
    elif kind == "boolean":
        default = True
    else:
        default = None
    if default is not None:
        if minimum is not None and default < minimum or maximum is not None and default > maximum:
            raise _invalid_metadata("@option 默认值超出 min/max 范围。", line)
        if choices is not None and default not in choices:
            raise _invalid_metadata("@option 默认值不在 choices 中。", line)
    if choices is not None and any(
        minimum is not None and choice < minimum or maximum is not None and choice > maximum for choice in choices
    ):
        raise _invalid_metadata("@option choices 包含超出 min/max 的值。", line)
    return StrategyOption(
        name, kind, description.strip(), optional or has_default, default, has_default, minimum, maximum, choices
    )


def parse_strategy(source: str) -> StrategyMetadata | None:
    """仅接受文件级 main(context) 声明；普通 Lua 文件继续按原始 chunk 执行。"""
    execution = parse_script_execution(source)
    lines = source.splitlines()
    marked = execution.mode == "tick" or any(_OPTION_MARKER.match(line) for line in lines)
    entry_lines = [line_number for line_number, line in enumerate(lines, 1) if _ENTRY.fullmatch(line)]
    has_entry = bool(entry_lines)
    if not marked and not has_entry:
        return None
    if not has_entry:
        raise _invalid_metadata("策略必须声明顶层 main(context) 入口。")
    if len(entry_lines) > 1:
        raise _invalid_metadata("策略只能声明一个 main(context) 入口。", entry_lines[1])

    options: list[StrategyOption] = []
    names: set[str] = set()
    flags: set[str] = set()
    for line_number, line in enumerate(lines, 1):
        if not _OPTION_MARKER.match(line):
            continue
        match = _OPTION.fullmatch(line)
        if match is None:
            raise _invalid_metadata("@option 格式应为 -- @option[type=int,opt] name 说明。", line_number)
        attributes, name, description = match.groups()
        flag = "--" + name.replace("_", "-")
        if name in names or not description.strip():
            raise _invalid_metadata("@option 名称不能重复，且必须提供说明。", line_number)
        if flag in flags or flag in _RESERVED_FLAGS:
            raise _invalid_metadata("@option 名称与通用 CLI 参数冲突。", line_number)
        if any(
            existing.type == "boolean" and flag == "--no-" + existing.name.replace("_", "-") for existing in options
        ):
            raise _invalid_metadata("@option 名称与 boolean 参数的 --no- 标记冲突。", line_number)
        names.add(name)
        option = _parse_option(attributes, name, description, line_number)
        if option.type == "boolean" and "--no-" + name.replace("_", "-") in flags:
            raise _invalid_metadata("boolean 参数的 --no- 标记与其他参数冲突。", line_number)
        flags.add(flag)
        options.append(option)
    return StrategyMetadata(tuple(options), execution)


def parse_options(metadata: StrategyMetadata, arguments: list[str]) -> JsonObject:
    """校验 script run/start 的动态 --name value 参数。"""
    by_flag = {option.flag: option for option in metadata.options}
    by_flag.update(
        {"--no-" + option.name.replace("_", "-"): option for option in metadata.options if option.type == "boolean"}
    )
    parsed: dict[str, JsonValue] = {}
    index = 0
    while index < len(arguments):
        token = arguments[index]
        flag, separator, inline = token.partition("=")
        option = by_flag.get(flag)
        if option is None:
            raise ClientError("invalid_strategy_option", f"未知的策略参数 {flag!r}。")
        if option.name in parsed:
            raise ClientError("invalid_strategy_option", f"策略参数 {flag} 只能提供一次。")
        if option.type == "boolean" and flag != option.flag:
            if separator:
                raise ClientError("invalid_strategy_option", f"布尔参数 {flag} 不接收值。")
            parsed[option.name] = False
            index += 1
            continue
        if (
            option.type == "boolean"
            and not separator
            and (index + 1 == len(arguments) or arguments[index + 1].startswith("--"))
        ):
            raw_value = "true"
        elif separator:
            raw_value = inline
        elif index + 1 < len(arguments):
            index += 1
            raw_value = arguments[index]
        else:
            raise ClientError("invalid_strategy_option", f"策略参数 {flag} 需要一个值。")
        try:
            value = _value(raw_value, option.type, 0)
        except ClientError as error:
            raise ClientError("invalid_strategy_option", f"策略参数 {flag} 的值无效：{error.message}") from error
        if (
            option.minimum is not None
            and value < option.minimum
            or option.maximum is not None
            and value > option.maximum
        ):
            raise ClientError("invalid_strategy_option", f"策略参数 {flag} 超出声明范围。")
        if option.choices is not None and value not in option.choices:
            raise ClientError("invalid_strategy_option", f"策略参数 {flag} 不在允许值中。")
        parsed[option.name] = value
        index += 1

    for option in metadata.options:
        if option.name in parsed:
            continue
        if option.has_default:
            parsed[option.name] = option.default
        elif not option.optional:
            raise ClientError("invalid_strategy_option", f"缺少必填策略参数 {option.flag}。")
    return parsed


def describe_strategy(path: Path, metadata: StrategyMetadata, package_root: Path | None = None) -> JsonObject:
    options: list[JsonObject] = []
    for option in metadata.options:
        value: JsonObject = {
            "name": option.name,
            "flag": option.flag,
            "type": option.type,
            "required": not option.optional,
            "description": option.description,
        }
        if option.has_default:
            value["default"] = option.default
        if option.minimum is not None:
            value["min"] = option.minimum
        if option.maximum is not None:
            value["max"] = option.maximum
        if option.choices is not None:
            value["choices"] = list(option.choices)
        options.append(value)
    target = path if package_root is None else package_root
    usage = "beidou-pilot script run/start " + str(target)
    for option in metadata.options:
        if option.type == "boolean":
            part = f"{option.flag}|--no-{option.name.replace('_', '-')}"
            if option.optional:
                part = f"[{part}]"
        else:
            part = f"{option.flag} <{option.type}>"
            if option.optional:
                part = f"[{part}]"
        usage += " " + part
    usage += " [--seconds N|--continuous]"
    result: JsonObject = {
        "file": str(target),
        "entry": "main(context)",
        "mode": metadata.mode,
        "tick": (
            {
                "gear": metadata.execution.gear,
                "budget_ms": metadata.execution.budget_ms,
                "overrun": metadata.execution.overrun,
                "abort_commit": metadata.execution.abort_commit,
            }
            if metadata.mode == "tick"
            else None
        ),
        "usage": usage,
        "options": options,
    }
    if package_root is not None:
        result["package_entry"] = str(path)
    return result


def _lua_string(value: str) -> str:
    escaped: list[str] = ['"']
    replacements = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f"}
    for character in value:
        codepoint = ord(character)
        if character in replacements:
            escaped.append(replacements[character])
        elif codepoint < 32 or codepoint == 127:
            escaped.append(f"\\{codepoint:03d}")
        else:
            escaped.append(character)
    escaped.append('"')
    return "".join(escaped)


def _lua_literal(value: JsonValue) -> str:
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _lua_string(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ClientError("invalid_strategy_context", "策略上下文含非有限数字。")
        return repr(value)
    if isinstance(value, list):
        return "{" + ",".join(_lua_literal(item) for item in value) + "}"
    return (
        "{"
        + ",".join(f"[{_lua_string(key)}]={_lua_literal(item)}" for key, item in value.items() if item is not None)
        + "}"
    )


def compile_strategy(source: str, options: JsonObject, scene: JsonObject, extra: JsonObject | None = None) -> str:
    values: JsonObject = {"options": options, "scene": scene}
    if extra:
        values.update(extra)
    context = _lua_literal(values)
    execution = parse_script_execution(source)
    if execution.mode == "tick":
        header, body = split_script_header(source)
        return (
            header
            + ("\n" if header and not header.endswith("\n") else "")
            + f"local __beidou_context = {context}\ndo\n"
            + body
            + '\nif type(main) ~= "function" then error("strategy_entry_missing") end\n'
            + "return {main=main,context=__beidou_context}\nend\n"
        )
    return (
        f"local __beidou_context = {context}\n"
        "local __beidou_state = game.state()\n"
        "if not (__beidou_state.ready and __beidou_state.instance_id == __beidou_context.scene.instance_id "
        "and __beidou_state.character and __beidou_state.character.id == __beidou_context.scene.character_id "
        "and __beidou_state.map_id == __beidou_context.scene.map_id "
        "and __beidou_state.scene_generation == __beidou_context.scene.scene_generation) then\n"
        '    error("strategy_scene_context_stale")\n'
        "end\n"
        "do\n"
        + source
        + '\nif type(main) ~= "function" then error("strategy_entry_missing") end\n'
        + "return main(__beidou_context)\nend\n"
    )


# 内置策略按需拼接的辅助文件；顺序即依赖顺序，_move 依赖 _terrain 的图与 _common 的动作检查。
_TRAVEL_COMMON = {"move_to.lua", "climb_to.lua", "enter_portal.lua", "walk_to.lua", "navigate.lua"}
_TRAVEL_TERRAIN = {"walk_to.lua", "navigate.lua"}
_TRAVEL_MOVE = {"walk_to.lua", "navigate.lua"}


def read_strategy_entry(path: Path) -> tuple[str, StrategyMetadata | None]:
    """读取入口文件本身；目录脚本包的入口不拼接内置辅助文件。"""
    try:
        source = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise ClientError(
            "invalid_script_file",
            "无法读取UTF-8 Lua入口，未发布执行请求。",
            {"path": str(path), "reason": str(error)},
        ) from error
    return source, parse_strategy(source)


def read_strategy_file(path: Path) -> tuple[str, StrategyMetadata | None]:
    shared = Path(__file__).resolve().parents[2] / "shared/scripts"
    directory = shared / "travel"
    resolved = path.resolve()
    source, metadata = read_strategy_entry(path)
    helpers: list[str] = []
    if resolved.parent == directory.resolve():
        if resolved.name in _TRAVEL_COMMON:
            helpers.append("_common.lua")
        if resolved.name in _TRAVEL_TERRAIN:
            helpers.append("_terrain.lua")
        if resolved.name in _TRAVEL_MOVE:
            helpers.append("_move.lua")
    elif resolved.parent == (shared / "combat").resolve() and resolved.name == "hunt.lua":
        helpers.append("_terrain.lua")
    if helpers:
        try:
            header, body = split_script_header(source)
            source = (
                header
                + ("\n" if header and not header.endswith("\n") else "")
                + "".join((directory / helper).read_text(encoding="utf-8") + "\n" for helper in helpers)
                + body
            )
        except (OSError, UnicodeError) as error:
            raise ClientError(
                "invalid_script_file",
                "无法读取UTF-8 Lua策略或其辅助文件，未发布执行请求。",
                {"path": str(path), "reason": str(error)},
            ) from error
    return source, metadata
