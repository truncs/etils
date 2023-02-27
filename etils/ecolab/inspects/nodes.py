# Copyright 2022 The etils Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""HTML builder for Python objects."""

from __future__ import annotations

import collections.abc
import dataclasses
import functools
import html
import types
from typing import Any, Callable, ClassVar, Generic, Type, TypeVar, Union
import uuid

from etils import enp
from etils.ecolab.inspects import attrs
from etils.ecolab.inspects import html_helper as H

_T = TypeVar('_T')


# All nodes are loaded globally and never cleared. Indeed, it's not possible
# to know when the Javascript is deleted (cell is cleared).
# It could create RAM issues by keeping object alive for too long. Could
# use weakref if this become an issue in practice.
_ALL_NODES: dict[str, Node] = {}


@dataclasses.dataclass
class Node:
  """Node base class.

  Each node correspond to a `<li>` element in the nested tree. When the node
  is expanded, `inner_html` is add the child nodes.

  Attributes:
    id: HTML id used to identify the node.
  """

  id: str = dataclasses.field(init=False)

  def __post_init__(self):
    # TODO(epot): Could likely have shorter/smarter uuids
    self.id = str(uuid.uuid1())
    _ALL_NODES[self.id] = self

  @classmethod
  def from_id(cls, id_: str) -> Node:
    """Returns the cached node from the HTML id."""
    return _ALL_NODES[id_]

  @classmethod
  def from_obj(cls, obj: object, *, name: str = '') -> ObjectNode:
    """Factory of a node from any object."""
    for sub_cls in [
        BuiltinNode,
        FnNode,
        MappingNode,
        SequenceNode,
        SetNode,
        ClsNode,
        ArrayNode,
        ExceptionNode,
        ObjectNode,
    ]:
      if isinstance(obj, sub_cls.MATCH_TYPES):
        break
    else:
      raise TypeError(f'Unexpected object {obj!r}.')

    return sub_cls(obj=obj, name=name)

  @property
  def header_html(self) -> str:
    """`<li>` one-line content."""
    raise NotImplementedError

  @property
  def inner_html(self) -> str:
    """Inner content when the item is expanded."""
    raise NotImplementedError

  def _li(self, *, clickable: bool = True) -> Callable[..., str]:
    """`<li>` section, called inside `header_html`."""
    if clickable:
      class_ = 'register-onclick-expand'
    else:
      class_ = 'caret-invisible'

    def apply(*content):
      return H.li(id=self.id)(H.span(class_=['caret', class_])(*content))

    return apply


@dataclasses.dataclass
class SubsectionNode(Node):
  """Expandable subsection of an object (to group object attributes).

  Example: `[[Methods]]`,...

  ```
  > obj:
    > ...
    > [[Methods]]
      > ...
    > [[Special attributes]]
      > ...
  ```
  """

  name: str
  childs: list[Node]

  @property
  def header_html(self) -> str:
    return self._li()(H.span(class_=['preview'])(f'[[{self.name}]]'))

  @property
  def inner_html(self) -> str:
    all_childs = [c.header_html for c in self.childs]
    return H.ul(class_=['collapsible'])(*all_childs)


@dataclasses.dataclass
class KeyValNode(Node):
  """The (k, v) items for `list`, `dict`."""

  key: object
  value: object

  # TODO(epot):
  # * Cleaner implementation.
  # * Built-ins should not be expandable.
  # * Make both key and value expandable (when not built-in) ?

  @property
  def header_html(self) -> str:
    return self._li()(
        _obj_html_repr(self.key), ': ', _obj_html_repr(self.value)
    )

  @property
  def inner_html(self) -> str:
    return Node.from_obj(self.value).inner_html


@dataclasses.dataclass
class ObjectNode(Node, Generic[_T]):
  """Any Python objects."""

  obj: _T
  name: str

  MATCH_TYPES: ClassVar[type[Any] | tuple[type[Any], ...]] = object

  @property
  def header_html(self) -> str:
    if self.is_root:
      prefix = ''
    else:
      prefix = f'{self.name}: '
    return self._li(clickable=not self.is_leaf)(
        H.span(class_=['key-main'])(f'{prefix}{self.header_repr}')
    )

  @property
  def inner_html(self) -> str:
    all_childs = [c.header_html for c in self.all_childs]
    return H.ul(class_=['collapsible'])(*all_childs)

  @property
  def all_childs(self) -> list[Node]:
    """Extract all attributes."""
    all_childs = [
        Node.from_obj(v, name=k) for k, v in attrs.get_attrs(self.obj).items()
    ]

    magic_attrs = []
    fn_attrs = []
    private_attrs = []
    val_attrs = []

    for c in all_childs:
      if c.name.startswith('__') and c.name.endswith('__'):
        magic_attrs.append(c)
      elif c.name.startswith('_'):
        private_attrs.append(c)
      elif isinstance(c, FnNode):
        fn_attrs.append(c)
      else:
        val_attrs.append(c)

    all_childs = val_attrs
    if fn_attrs:
      all_childs.append(SubsectionNode(childs=fn_attrs, name='Methods'))
    if private_attrs:
      all_childs.append(SubsectionNode(childs=private_attrs, name='Private'))
    if magic_attrs:
      all_childs.append(
          SubsectionNode(childs=magic_attrs, name='Special attributes')
      )

    return all_childs

  @property
  def header_repr(self) -> str:
    return _obj_html_repr(self.obj)

  @property
  def is_root(self) -> bool:
    """Returns `True` if the node is top-level."""
    return not bool(self.name)

  @property
  def is_leaf(self) -> bool:
    """Returns `True` if the node cannot be recursed into."""
    return False


@dataclasses.dataclass
class BuiltinNode(ObjectNode[Union[int, float, bool, str, bytes, None]]):  # pytype: disable=bad-concrete-type
  """`int`, `float`, `bytes`, `str`,..."""

  MATCH_TYPES = (type(None), int, float, bool, str, bytes, type(...))

  # TODO(epot): For subclasses, print the actual type somewhere ? Same for list,
  # dict,... ?

  @property
  def is_leaf(self) -> bool:
    # Can recurse into built-ins only if they are roots
    return not self.is_root


@dataclasses.dataclass
class MappingNode(ObjectNode[collections.abc.Mapping]):  # pytype: disable=bad-concrete-type
  """`dict` like."""

  MATCH_TYPES = (dict, collections.abc.Mapping)

  @property
  def all_childs(self) -> list[Node]:
    return [
        KeyValNode(key=k, value=v) for k, v in self.obj.items()
    ] + super().all_childs


@dataclasses.dataclass
class SetNode(ObjectNode[collections.abc.Set]):  # pytype: disable=bad-concrete-type
  """`set` like."""

  MATCH_TYPES = (set, frozenset, collections.abc.Set)

  @property
  def all_childs(self) -> list[Node]:
    return [
        KeyValNode(key=id(v), value=v) for v in self.obj
    ] + super().all_childs


@dataclasses.dataclass
class SequenceNode(ObjectNode[Union[list, tuple]]):
  """`list` like."""

  MATCH_TYPES = (list, tuple)

  @property
  def all_childs(self) -> list[Node]:
    return [
        KeyValNode(key=i, value=v) for i, v in enumerate(self.obj)
    ] + super().all_childs


@dataclasses.dataclass
class FnNode(ObjectNode[Callable[..., Any]]):
  """Function."""

  MATCH_TYPES = (
      types.FunctionType,
      types.BuiltinFunctionType,
      types.MethodType,
      types.MethodDescriptorType,
      functools.partial,
  )

  # TODO(epot): Print `<red>f</red>`, docstring, signature


@dataclasses.dataclass
class ArrayNode(ObjectNode[enp.typing.Array]):
  """Array."""

  MATCH_TYPES = enp.lazy.LazyArray

  # TODO(epot): When expanded, print the array values, or also in the one-line
  # description ?


@dataclasses.dataclass
class ClsNode(ObjectNode[Type[Any]]):
  """Type."""

  MATCH_TYPES = type

  # TODO(epot): Add link to source code

  @property
  def all_childs(self) -> list[Node]:
    # Add `[[mro]]` subsection
    return super().all_childs + [
        SubsectionNode(
            childs=[Node.from_obj(cls) for cls in self.obj.mro()],
            name='mro',
        )
    ]


@dataclasses.dataclass
class ExceptionNode(ObjectNode[attrs.ExceptionWrapper]):
  """Exception."""

  MATCH_TYPES = attrs.ExceptionWrapper

  # TODO(epot): Could expand with the traceback

  @property
  def is_leaf(self) -> bool:
    return True


def _obj_html_repr(obj: object) -> str:
  """Returns the object representation."""
  if isinstance(obj, type(None)):
    type_ = 'null'
  elif isinstance(obj, type(...)):
    type_ = 'null'
  elif isinstance(obj, (int, float)):
    type_ = 'number'
  elif isinstance(obj, bool):
    type_ = 'boolean'
  elif isinstance(obj, (str, bytes)):
    type_ = 'string'
    obj = _truncate_long_str(repr(obj))
  elif isinstance(obj, enp.lazy.LazyArray):
    type_ = 'number'
    obj = enp.ArraySpec.from_array(obj)
  elif isinstance(obj, attrs.ExceptionWrapper):
    type_ = 'error'
    obj = obj.e
  else:
    type_ = 'preview'
    try:
      obj = repr(obj)
    except Exception as e:  # pylint: disable=broad-except
      return _obj_html_repr(attrs.ExceptionWrapper(e))
    obj = _truncate_long_str(obj)

  if not isinstance(obj, str):
    obj = repr(obj)
    obj = html.escape(obj)
  return H.span(class_=[type_])(obj)


def _truncate_long_str(value: str) -> str:
  """Truncate long strings."""
  value = html.escape(value)
  # TODO(epot): Could have a better expand section which truncate long string
  # (e.g. > 100 lines)
  # TODO(epot): Better CSS (with button)
  if len(value) > 80:
    return H.span(class_=['content-switch'])(
        # Short version
        H.span(class_=['content-version-short'])(
            value[:80]
            + H.span(class_='content-switch-expand register-onclick-switch')(
                '...'
            )
        ),
        # Long version
        H.span(class_='content-version-long register-onclick-switch')(value),
    )
  else:
    return value
