from __future__ import annotations

from abc import abstractmethod, ABC
from dataclasses import dataclass
from enum import Flag, auto
from itertools import combinations
from textwrap import indent
from typing import Iterable, FrozenSet, Optional, Tuple, List, Union, Any

from greenery.fsm import fsm, anything_else, epsilon, null
from simple_parser import SimpleParser, nomatch


class _REFlags(Flag):
    CASE_INSENSITIVE = I = auto()
    SINGLE_LINE = S = auto()
    MULTILINE = M = auto()


_flags = {
    'i': _REFlags.I,
    's': _REFlags.S,
    'm': _REFlags.M,
}


def _get_flags(plus: str) -> _REFlags:
    res = _REFlags(0)
    for c in plus:
        res |= _flags[c]
    return res


def _combine_flags(base: _REFlags, added: _REFlags, removed: _REFlags):
    base |= added
    base &= ~removed
    # TODO: Check for incorrect combinations (aLu)
    return base


@dataclass(frozen=True)
class _BasePattern(ABC):
    __slots__ = '_alphabet_cache', '_prefix_cache', '_lengths_cache'

    @abstractmethod
    def to_fsm(self, alphabet=None, prefix_postfix=None, flags=None) -> fsm:
        raise NotImplementedError

    @abstractmethod
    def _get_alphabet(self) -> Iterable:
        raise NotImplementedError

    @property
    def alphabet(self) -> FrozenSet:
        if not hasattr(self, '_alphabet_cache'):
            super(_BasePattern, self).__setattr__('_alphabet_cache', frozenset(self._get_alphabet()))
        return self._alphabet_cache

    @abstractmethod
    def _get_prefix_postfix(self) -> Tuple[int, Optional[int]]:
        raise NotImplementedError

    @property
    def prefix_postfix(self) -> Tuple[int, Optional[int]]:
        """Returns the number of dots that have to be pre-/postfixed to support look(aheads|backs)"""
        if not hasattr(self, '_prefix_cache'):
            super(_BasePattern, self).__setattr__('_prefix_cache', self._get_prefix_postfix())
        return self._prefix_cache

    @abstractmethod
    def _get_lengths(self) -> Tuple[int, Optional[int]]:
        raise NotImplementedError

    @property
    def lengths(self) -> Tuple[int, Optional[int]]:
        """Returns the minimum and maximum length that this pattern can match
         (maximum can be None bei infinite length)"""
        if not hasattr(self, '_lengths_cache'):
            super(_BasePattern, self).__setattr__('_lengths_cache', self._get_lengths())
        return self._lengths_cache


class _Repeatable(_BasePattern, ABC):
    pass


@dataclass(frozen=True)
class _CharGroup(_Repeatable):
    """Represents the smallest possible pattern that can be matched: A single char.
    Direct port from the lego module"""
    chars: FrozenSet[str]
    negated: bool
    __slots__ = 'chars', 'negated'

    def _get_alphabet(self, alphabet=None) -> Iterable:
        yield from self.chars
        yield anything_else

    def _get_prefix_postfix(self) -> Tuple[int, Optional[int]]:
        return 0, 0

    def _get_lengths(self) -> Tuple[int, Optional[int]]:
        return 1, 1

    def to_fsm(self, alphabet=None, prefix_postfix=None, flags=None) -> fsm:
        if alphabet is None:
            alphabet = self.alphabet
        if prefix_postfix is None:
            prefix_postfix = self.prefix_postfix
        if prefix_postfix != (0, 0):
            raise ValueError("Can not have prefix/postfix on CharGroup-level")
        if flags is not None:
            raise NotImplementedError(flags)

        # 0 is initial, 1 is final

        # If negated, make a singular FSM accepting any other characters
        if self.negated:
            mapping = {
                0: dict([(symbol, 1) for symbol in alphabet - self.chars]),
            }

        # If normal, make a singular FSM accepting only these characters
        else:
            mapping = {
                0: dict([(symbol, 1) for symbol in self.chars]),
            }

        return fsm(
            alphabet=alphabet,
            states={0, 1},
            initial=0,
            finals={1},
            map=mapping,
        )


@dataclass(frozen=True)
class _CompositeCharGroup(_Repeatable):
    """Represents the smallest possible pattern that can be matched: A single char.
    Is a combination of different CharGroups to make life easier"""
    groups: Tuple[_CharGroup, ...]
    negate: bool

    def _get_alphabet(self) -> Iterable:
        for g in self.groups:
            yield from g.alphabet
        yield anything_else

    def _get_prefix_postfix(self) -> Tuple[int, Optional[int]]:
        return 0, 0

    def _get_lengths(self) -> Tuple[int, Optional[int]]:
        return 1, 1

    def to_fsm(self, alphabet=None, prefix_postfix=None, flags=None) -> fsm:
        if alphabet is None:
            alphabet = self.alphabet
        if prefix_postfix is None:
            prefix_postfix = self.prefix_postfix
        if prefix_postfix != (0, 0):
            raise ValueError("Can not have prefix/postfix on CharGroup-level")

        base = fsm.union(*(g.to_fsm(alphabet, flags=flags) for g in self.groups))
        if self.negate:
            return _ALL.to_fsm(alphabet).different(base)
        else:
            return base


@dataclass(frozen=True)
class __DotCls(_BasePattern):

    def to_fsm(self, alphabet=None, prefix_postfix=None, flags=None) -> fsm:
        if alphabet is None:
            alphabet = self.alphabet
        if flags is None or not flags & _REFlags.SINGLE_LINE:
            chars = alphabet - {'\n'}
        else:
            chars = alphabet
        return fsm(
            alphabet=alphabet,
            states={0, 1},
            initial=0,
            finals={1},
            map={0: {symbol: 1 for symbol in chars}},
        )

    def _get_alphabet(self) -> Iterable:
        yield '\n'
        yield anything_else

    def _get_prefix_postfix(self) -> Tuple[int, Optional[int]]:
        return 0, 0

    def _get_lengths(self) -> Tuple[int, Optional[int]]:
        return 1, 1


@dataclass(frozen=True)
class __EmptyCls(_BasePattern):

    def to_fsm(self, alphabet=None, prefix_postfix=None, flags=None) -> fsm:
        if alphabet is None:
            alphabet = self.alphabet
        return epsilon(alphabet)

    def _get_alphabet(self) -> Iterable:
        yield '\n'
        yield anything_else

    def _get_prefix_postfix(self) -> Tuple[int, Optional[int]]:
        return 0, 0

    def _get_lengths(self) -> Tuple[int, Optional[int]]:
        return 1, 1


_DOT = __DotCls()
_EMPTY = __EmptyCls()
_NONE = _CharGroup(frozenset(""), False)
_ALL = _CharGroup(frozenset(""), True)
_CHAR_GROUPS = {
    'w': _CharGroup(frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"), False),
    'W': _CharGroup(frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"), True),
    'd': _CharGroup(frozenset("0123456789"), False),
    'D': _CharGroup(frozenset("0123456789"), True),
    's': _CharGroup(frozenset(" \t\n\r\f\v"), False),
    'S': _CharGroup(frozenset(" \t\n\r\f\v"), True),

    'a': _CharGroup(frozenset("\a"), False),
    'b': _CharGroup(frozenset("\b"), False),
    'f': _CharGroup(frozenset("\f"), False),
    'n': _CharGroup(frozenset("\n"), False),
    'r': _CharGroup(frozenset("\r"), False),
    't': _CharGroup(frozenset("\t"), False),
    'v': _CharGroup(frozenset("\v"), False),
}


@dataclass(frozen=True)
class _Repeated(_BasePattern):
    """Represents a repeated pattern. `base` can be matched from `min` to `max` times. 
    `max` may be None to signal infinite"""
    base: _Repeatable
    min: int
    max: Optional[int]

    def __str__(self):
        return f"Repeated[{self.min}:{self.max if self.max is not None else ''}]:\n" \
            f"{indent(str(self.base), '    ')}"

    def _get_alphabet(self) -> Iterable:
        return self.base.alphabet

    def _get_prefix_postfix(self) -> Tuple[int, Optional[int]]:
        return self.base.prefix_postfix

    def _get_lengths(self) -> Tuple[int, Optional[int]]:
        l, h = self.base.lengths
        return l * self.min, (h * self.max if None not in (h, self.max) else None)

    def to_fsm(self, alphabet=None, prefix_postfix=None, flags=None) -> fsm:
        if alphabet is None:
            alphabet = self.alphabet
        if prefix_postfix is None:
            prefix_postfix = self.prefix_postfix
        if prefix_postfix != (0, 0):
            raise ValueError("Can not have prefix/postfix on CharGroup-level")

        unit = self.base.to_fsm(alphabet)
        mandatory = unit * self.min
        if self.max is None:
            optional = unit.star()
        else:
            optional = epsilon(alphabet) | unit
            optional *= (self.max - self.min)
        return mandatory + optional


_ALL_STAR = _Repeated(_ALL, 0, None)


@dataclass(frozen=True)
class _NonCapturing:
    """Represents a lookahead/lookback. Matches `inner` without 'consuming' anything. Can be negated.
    Only valid inside a `_Concatenation`"""
    inner: _BasePattern
    backwards: bool
    negate: bool
    __slots__ = 'inner', 'backwards', 'negate'

    @property
    def alphabet(self):
        return self.inner.alphabet


@dataclass(frozen=True)
class _Concatenation(_BasePattern):
    """Represents multiple Patterns that have to be match in a row. Can contain `_NonCapturing`"""
    parts: Tuple[Union[_BasePattern, _NonCapturing], ...]
    __slots__ = 'parts',

    def __str__(self):
        return "Concatenation:\n" + "\n".join(indent(str(p), '  ') for p in self.parts)

    def _get_alphabet(self) -> Iterable:
        for p in self.parts:
            yield from p.alphabet
        yield anything_else

    def _get_prefix_postfix(self) -> Tuple[int, Optional[int]]:
        pre = 0  # What is the longest a lookback could stick out over the beginning?
        off = 0  # How many chars have been consumed, e.g what is the minimum length?
        for p in self.parts:
            if not isinstance(p, _NonCapturing):
                off += p.lengths[0]
            elif p.backwards:
                a, b = p.inner.lengths
                if a != b:
                    print(p.inner)
                    raise ValueError(f"lookbacks have to have fixed length {(a, b)}")
                req = a - off
                if req > pre:
                    pre = req
        post = 0
        off = 0
        for p in reversed(self.parts):
            if not isinstance(p, _NonCapturing):
                off += p.lengths[0]
            elif not p.backwards:
                a, b = p.inner.lengths
                if b is None:
                    req = a - off  # TODO: is this correct?
                else:
                    req = b - off
                if req > post:
                    post = req
        return pre, post

    def _get_lengths(self) -> Tuple[int, Optional[int]]:
        l, h = 0, 0
        for p in self.parts:
            if not isinstance(p, _NonCapturing):
                pl, ph = p.lengths
                l += pl
                h = h + ph if None not in (h, ph) else None
        return l, h

    def to_fsm(self, alphabet=None, prefix_postfix=None, flags=None) -> fsm:
        if alphabet is None:
            alphabet = self.alphabet
        if prefix_postfix is None:
            prefix_postfix = self.prefix_postfix

        all = _ALL.to_fsm(alphabet)
        all_star = _ALL_STAR.to_fsm(alphabet)
        fsm_parts = []
        empty = epsilon(alphabet)
        current = empty
        current += all.times(prefix_postfix[0])
        for part in self.parts:
            if isinstance(part, _NonCapturing):
                inner = part.inner.to_fsm(alphabet, (0, 0), flags)
                if part.backwards:
                    raise NotImplementedError("lookbacks are not implemented")
                else:
                    try:
                        inner.cardinality()
                    except OverflowError:
                        raise NotImplementedError("Can not deal with infinite length lookaheads")
                    fsm_parts.append((None, current))
                    fsm_parts.append((part, inner))
                    current = empty
            else:
                current += part.to_fsm(alphabet, (0, 0),flags)
        current += all.times(prefix_postfix[1])
        result = current
        for m, f in reversed(fsm_parts):
            print(result)
            if m is None:
                result = f + result
            else:
                assert isinstance(m, _NonCapturing) and not m.backwards
                if m.negate:
                    result = result.difference(f)
                else:
                    result = result.intersection(f + all_star)
        return result


@dataclass(frozen=True)
class Pattern(_Repeatable):
    options: Tuple[_BasePattern, ...]
    added_flags: _REFlags = _REFlags(0)
    removed_flags: _REFlags = _REFlags(0)

    def __str__(self):
        return "Pattern:\n" + "\n".join(indent(str(o), '  ') for o in self.options)

    def _get_alphabet(self) -> Iterable:
        for o in self.options:
            yield from o.alphabet
        yield anything_else

    def _get_lengths(self) -> Tuple[int, Optional[int]]:
        l, h = None, 0
        for o in self.options:
            ol, oh = o.lengths
            if l is None or ol < l:
                l = ol
            if oh is None or (h is not None and oh > h):
                h = oh
        return l, h

    def _get_prefix_postfix(self) -> Tuple[int, Optional[int]]:
        pre, post = 0, 0
        for o in self.options:
            opre, opost = o.prefix_postfix
            if opre > pre:
                pre = opre
            if opost is None or (post is not None and opost > post):
                post = opost
        return pre, post

    def to_fsm(self, alphabet=None, prefix_postfix=None, flags=None) -> fsm:
        if alphabet is None:
            alphabet = self.alphabet
        if prefix_postfix is None:
            prefix_postfix = self.prefix_postfix
        if flags is None:
            flags = _REFlags(0)
        flags = _combine_flags(flags, self.added_flags, self.removed_flags)
        result = self.options[0].to_fsm(alphabet, prefix_postfix, flags)
        for o in self.options[1:]:
            result |= o.to_fsm(alphabet, prefix_postfix, flags)
        return result

    def with_flags(self, added: _REFlags, removed: _REFlags = _REFlags(0)) -> Pattern:
        return self.__class__(self.options, added, removed)


class _ParsePattern(SimpleParser[Pattern]):
    SPECIAL_CHARS_STANDARD: FrozenSet[str] = frozenset({
        '+', '?', '*', '.', '$', '^', '\\', '(', ')', '[', ']', '{', '}'
    })
    SPECIAL_CHARS_INNER: FrozenSet[str] = frozenset({
        '\\', '[', ']', '-'
    })
    RESERVED_ESCAPES: FrozenSet[str] = frozenset({
        'u', 'U', 'A', 'Z', 'b', 'B'
    })

    def __init__(self, data: str):
        super(_ParsePattern, self).__init__(data)
        self.flags = None

    def start(self):
        self.flags = None
        p = self.pattern()
        if self.flags is not None:
            p = p.with_flags(self.flags)
        return p

    def pattern(self):
        options = [self.conc()]
        while self.static_b('|'):
            options.append(self.conc())
        return Pattern(tuple(options))

    def conc(self):
        parts = []
        while True:
            try:
                parts.append(self.obj())
            except nomatch:
                break
        return _Concatenation(tuple(parts))

    def obj(self):
        if self.static_b("("):
            return self.group()
        return self.repetition(self.atom())

    def group(self):
        if self.static_b("?"):
            return self.extension_group()
        else:
            p = self.pattern()
            self.static(")")
            return self.repetition(p)

    def extension_group(self):
        c = self.any()
        if c in 'aiLmsux-':
            self.index -= 1
            added_flags = self.multiple('aiLmsux', 0, None)
            if self.static_b('-'):
                removed_flags = self.multiple('aiLmsux', 1, None)
            else:
                removed_flags = ''
            if self.static_b(':'):
                p = self.pattern()
                p = p.with_flags(_get_flags(added_flags), _get_flags(removed_flags))
                self.static(")")
                return self.repetition(p)
            elif removed_flags != '':
                raise nomatch
            else:
                self.static(')')
                self.flags = _get_flags(added_flags)
                return _EMPTY
        elif c == ':':
            p = self.pattern()
            self.static(")")
            return self.repetition(p)
        elif c == 'P':
            if self.static_b('<'):
                self.multiple('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_', 1, None)
                self.static('>')
                p = self.pattern()
                self.static(")")
                return self.repetition(p)
            elif self.static_b('='):
                raise NotImplementedError("Group references are not implemented")
        elif c == '#':
            while not self.static_b(')'):
                self.any()
        elif c == '=':
            p = self.pattern()
            self.static(")")
            return _NonCapturing(p, False, False)
        elif c == '!':
            p = self.pattern()
            self.static(")")
            return _NonCapturing(p, False, True)
        elif c == '<':
            c = self.any()
            if c == '=':
                p = self.pattern()
                self.static(")")
                return _NonCapturing(p, True, False)
            elif c == '!':
                p = self.pattern()
                self.static(")")
                return _NonCapturing(p, True, True)
        elif c == '(':
            raise NotImplementedError("Conditional matching is not implmented")
        else:
            raise ValueError(f"Unknown group-extension: {c!r} (Context: {self.data[self.index - 3:self.index + 5]!r}")

    def atom(self):
        if self.static_b("["):
            return self.repetition(self.chargroup())
        elif self.static_b("\\"):
            return self.repetition(self.escaped())
        elif self.static_b("."):
            return self.repetition(_DOT)
        else:
            c = self.any_but(*self.SPECIAL_CHARS_STANDARD)
            return self.repetition(_CharGroup(frozenset({c}), False))

    def repetition(self, base: _Repeatable):
        if self.static_b("*"):
            if self.static_b("?"):
                pass
            return _Repeated(base, 0, None)
        elif self.static_b("+"):
            if self.static_b("?"):
                pass
            return _Repeated(base, 1, None)
        elif self.static_b("?"):
            if self.static_b("?"):
                pass
            return _Repeated(base, 0, 1)
        elif self.static_b("{"):
            try:
                n = self.number()
            except nomatch:
                n = 0
            if self.static_b(','):
                try:
                    m = self.number()
                except nomatch:
                    m = None
            else:
                m = n
            self.static("}")
            if self.static_b('?'):
                pass
            return _Repeated(base, n, m)
        else:
            return base

    def number(self) -> int:
        return int(self.multiple("0123456789", 1, None))

    def escaped(self, inner=False):
        if self.static_b("x"):
            n = self.multiple("0123456789", 2, 2)
            c = chr(int(n, 16))
            return _CharGroup(frozenset({c}), False)
        if self.static_b("0"):
            n = self.multiple("01234567", 1, 2)
            c = chr(int(n, 8))
            return _CharGroup(frozenset({c}), False)
        if not inner:
            try:
                n = self.multiple("01234567", 3, 3)
            except nomatch:
                pass
            else:
                c = chr(int(n, 8))
                return _CharGroup(frozenset({c}), False)
            try:
                n = self.multiple("0123456789", 1, 2)
            except nomatch:
                pass
            else:
                raise NotImplementedError("Group references are not implemented")
        else:
            try:
                n = self.multiple("01234567", 1, 3)
            except nomatch:
                pass
            else:
                c = chr(int(n, 8))
                return _CharGroup(frozenset({c}), False)
        if not inner:
            try:
                c = self.anyof(*self.RESERVED_ESCAPES)
            except nomatch:
                pass
            else:
                raise NotImplementedError(f"Escape \\{c} is not implemented")
        try:
            c = self.anyof(*_CHAR_GROUPS)
        except nomatch:
            pass
        else:
            return _CHAR_GROUPS[c]
        c = self.any_but("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
        if c.isalpha():
            raise nomatch
        return _CharGroup(frozenset(c), False)

    def chargroup(self):
        if self.static_b("^"):
            negate = True
        else:
            negate = False
        groups = []
        while True:
            try:
                groups.append(self.chargroup_inner())
            except nomatch:
                break
        self.static("]")
        if len(groups) > 1:
            return _CompositeCharGroup(tuple(groups), negate)
        else:
            return tuple(groups)[0]

    def chargroup_inner(self) -> _CharGroup:
        start = self.index
        if self.static_b('\\'):
            base = self.escaped(True)
        else:
            base = _CharGroup(frozenset(self.any_but(*self.SPECIAL_CHARS_INNER)), False)
        if self.static_b('-'):
            if self.static_b('\\'):
                end = self.escaped(True)
            else:
                end = _CharGroup(frozenset(self.any_but(*self.SPECIAL_CHARS_INNER)), False)
            if len(base.chars) != len(end.chars) != 1:
                raise ValueError(f"Invalid Character-range: {self.data[start:self.index]}")
            low, high = ord(*base.chars), ord(*end.chars)
            if low > high:
                raise ValueError(f"Invalid Character-range: {self.data[start:self.index]}")
            return _CharGroup(frozenset((chr(i) for i in range(low, high + 1))), False)
        return base


def parse_pattern(pattern: str) -> Pattern:
    p = _ParsePattern(pattern)
    return p.parse()


def compare_patterns(*patterns: Pattern) -> Iterable[Tuple[Pattern, Pattern]]:
    alphabet = frozenset(c for p in patterns for c in p.alphabet)
    prefix_postfix_s = [p.prefix_postfix for p in patterns]
    prefix_postfix = max(p[0] for p in prefix_postfix_s), max(p[1] for p in prefix_postfix_s)
    all_star = _ALL_STAR.to_fsm(alphabet)
    fsms = [(p, p.to_fsm(alphabet, prefix_postfix)) for p in patterns]
    for (ka, fa), (kb, fb) in combinations(fsms, 2):
        fa: fsm
        if not fa.isdisjoint(fb):
            yield (ka, kb)
