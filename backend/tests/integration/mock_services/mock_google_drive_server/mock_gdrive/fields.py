"""Partial responses: the `fields` parameter of Google APIs.

`parse_fields("nextPageToken, files(id, owners(emailAddress))")` gives a mask
that `apply_mask` uses to keep only those keys. `*` keeps every key at its level.
"""

from typing import Any

FieldMask = dict[str, "FieldMask | None"]


class FieldsError(ValueError):
    pass


class _Parser:
    def __init__(self, spec: str) -> None:
        self._spec = spec
        self._i = 0

    def parse(self) -> FieldMask:
        mask = self._list()
        if self._i != len(self._spec):
            raise FieldsError(f"Invalid fields value {self._spec!r}")
        return mask

    def _list(self) -> FieldMask:
        mask: FieldMask = {}
        while True:
            self._skip_space()
            self._item(mask)
            self._skip_space()
            if self._i < len(self._spec) and self._spec[self._i] == ",":
                self._i += 1
                continue
            return mask

    def _item(self, mask: FieldMask) -> None:
        path = [self._name()]
        while self._i < len(self._spec) and self._spec[self._i] == "/":
            self._i += 1
            path.append(self._name())
        self._skip_space()
        sub: FieldMask | None = None
        if self._i < len(self._spec) and self._spec[self._i] == "(":
            self._i += 1
            sub = self._list()
            if self._i >= len(self._spec) or self._spec[self._i] != ")":
                raise FieldsError(f"Missing ')' in {self._spec!r}")
            self._i += 1
        for name in reversed(path[1:]):
            sub = {name: sub}
        _merge(mask, path[0], sub)

    def _name(self) -> str:
        self._skip_space()
        start = self._i
        while self._i < len(self._spec) and self._spec[self._i] not in ",()/ ":
            self._i += 1
        name = self._spec[start : self._i]
        if not name:
            raise FieldsError(f"Invalid fields value {self._spec!r}")
        return name

    def _skip_space(self) -> None:
        while self._i < len(self._spec) and self._spec[self._i].isspace():
            self._i += 1


def _merge(mask: FieldMask, name: str, sub: "FieldMask | None") -> None:
    if name not in mask:
        mask[name] = sub
        return
    current = mask[name]
    if current is None or sub is None:
        mask[name] = None
        return
    for key, value in sub.items():
        _merge(current, key, value)


def parse_fields(spec: str | None) -> FieldMask | None:
    """None keeps everything."""
    if spec is None or spec.strip() in ("", "*"):
        return None
    return _Parser(spec).parse()


def apply_mask(value: Any, mask: FieldMask | None) -> Any:
    if mask is None:
        return value
    if isinstance(value, list):
        return [apply_mask(item, mask) for item in value]
    if not isinstance(value, dict):
        return value
    if "*" in mask:
        result = dict(value)
        for key, sub in mask.items():
            if key != "*" and key in value:
                result[key] = apply_mask(value[key], sub)
        return result
    return {
        key: apply_mask(value[key], sub) for key, sub in mask.items() if key in value
    }
