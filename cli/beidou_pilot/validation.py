"""入口参数校验：在边界集中检查并返回已校验的值。"""

from collections.abc import Mapping
from typing import Any

from .errors import ClientError

_MISSING = object()


class ValidationFailure(Exception):
    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason


class Field:
    def __init__(self, *, required: bool = True, default: Any = _MISSING) -> None:
        self.required = required
        self.default = default

    def parse(self, value: Any, path: str) -> Any:
        raise NotImplementedError


class String(Field):
    def __init__(self, *, nonempty: bool = True, no_control: bool = False, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.nonempty = nonempty
        self.no_control = no_control

    def parse(self, value: Any, path: str) -> str:
        if not isinstance(value, str):
            raise ValidationFailure(path, "须为字符串")
        if self.nonempty and not value:
            raise ValidationFailure(path, "不能为空")
        if self.no_control and any(ord(ch) < 32 for ch in value):
            raise ValidationFailure(path, "不能包含控制字符")
        return value


class Integer(Field):
    def __init__(self, *, minimum: int | None = None, maximum: int | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.minimum = minimum
        self.maximum = maximum

    def parse(self, value: Any, path: str) -> int:
        if type(value) is not int:
            raise ValidationFailure(path, "须为整数")
        if self.minimum is not None and value < self.minimum:
            raise ValidationFailure(path, f"须大于等于 {self.minimum}")
        if self.maximum is not None and value > self.maximum:
            raise ValidationFailure(path, f"须小于等于 {self.maximum}")
        return value


class Object(Field):
    def __init__(self, fields: Mapping[str, Field], *, allow_extra: bool = False, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.fields = dict(fields)
        self.allow_extra = allow_extra

    def parse(self, value: Any, path: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValidationFailure(path or "值", "须为对象")
        extra = set(value) - set(self.fields)
        if extra and not self.allow_extra:
            raise ValidationFailure(path or "值", "包含未知字段: " + ", ".join(sorted(extra)))
        parsed: dict[str, Any] = {}
        for name, field in self.fields.items():
            field_path = f"{path}.{name}" if path else name
            if name in value:
                parsed[name] = field.parse(value[name], field_path)
            elif field.default is not _MISSING:
                parsed[name] = field.default
            elif field.required:
                raise ValidationFailure(field_path, "缺少字段")
        return parsed


def validate(value: Any, schema: Field, *, code: str, label: str) -> Any:
    try:
        return schema.parse(value, "")
    except ValidationFailure as error:
        field = error.path or "值"
        raise ClientError(code, f"{label}无效：{field} {error.reason}",
                          {"field": field, "reason": error.reason}) from error
