#
# This file is part of the PyMeasure package.
#
# Copyright (c) 2013-2022 PyMeasure Developers
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

"""Pure-Python sequencer logic extracted from
``display/widgets/sequencer_widget.py``.

Zero Qt imports.  The public surface consists of:

- :data:`SAFE_FUNCTIONS` – the restricted evaluation namespace.
- :class:`SequenceEvaluationException` – raised when a sequence string
  cannot be evaluated safely.
- :func:`eval_string` – evaluate a single sequence string inside the
  restricted namespace and return a ``numpy.ndarray``.
- :func:`get_sequence` – convert a list-of-dicts tree into a flat list of
  parameter-combination dicts.
- :func:`parse_sequence_file` – parse the dash-indented text file format and
  return a tree suitable for :func:`get_sequence`.
"""

import logging
import re
from itertools import product

import numpy

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())


# ---------------------------------------------------------------------------
# Safe evaluation namespace
# ---------------------------------------------------------------------------

#: Mapping of names that are available inside sequence strings evaluated by
#: :func:`eval_string`.  The set mirrors the original ``SequencerWidget``
#: exactly so that existing sequence files remain compatible.
SAFE_FUNCTIONS = {
    "range":    range,
    "sorted":   sorted,
    "list":     list,
    "bool":     bool,
    "arange":   numpy.arange,
    "linspace": numpy.linspace,
    "logspace": numpy.logspace,
    "arccos":   numpy.arccos,
    "arcsin":   numpy.arcsin,
    "arctan":   numpy.arctan,
    "arctan2":  numpy.arctan2,
    "ceil":     numpy.ceil,
    "cos":      numpy.cos,
    "cosh":     numpy.cosh,
    "degrees":  numpy.degrees,
    "e":        numpy.e,
    "exp":      numpy.exp,
    "fabs":     numpy.fabs,
    "floor":    numpy.floor,
    "fmod":     numpy.fmod,
    "frexp":    numpy.frexp,
    "hypot":    numpy.hypot,
    "ldexp":    numpy.ldexp,
    "log":      numpy.log,
    "log10":    numpy.log10,
    "modf":     numpy.modf,
    "pi":       numpy.pi,
    "power":    numpy.power,
    "radians":  numpy.radians,
    "sin":      numpy.sin,
    "sinh":     numpy.sinh,
    "sqrt":     numpy.sqrt,
    "tan":      numpy.tan,
    "tanh":     numpy.tanh,
}


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class SequenceEvaluationException(Exception):
    """Raised when the evaluation of a sequence string goes wrong."""
    pass


# ---------------------------------------------------------------------------
# eval_string
# ---------------------------------------------------------------------------

def eval_string(string, name=None, depth=None):
    """Evaluate *string* inside a restricted namespace and return a
    ``numpy.ndarray``.

    The evaluation is restricted to the functions listed in
    :data:`SAFE_FUNCTIONS`; no builtins or globals are available, which
    prevents execution of arbitrary code.

    :param string: The expression to evaluate, e.g. ``"linspace(0, 1, 10)"``.
    :param name: Parameter name – used only in error messages.
    :param depth: Tree depth – used only in error messages.

    :returns: ``numpy.ndarray`` containing the evaluated values.

    :raises SequenceEvaluationException: When *string* is empty or cannot be
        evaluated due to a ``TypeError``, ``SyntaxError``, or ``ValueError``.
    """
    if not string or not string.strip():
        log.error(
            "No sequence entered for parameter '%s', depth %s", name, depth
        )
        raise SequenceEvaluationException(
            "Empty sequence string for parameter '{}', depth {}".format(name, depth)
        )

    try:
        result = eval(string, {"__builtins__": None}, SAFE_FUNCTIONS)  # noqa: S307
    except TypeError:
        log.error(
            "TypeError, likely a typo in one of the functions for parameter '%s', depth %s",
            name, depth,
        )
        raise SequenceEvaluationException(
            "TypeError evaluating sequence for parameter '{}', depth {}".format(name, depth)
        )
    except SyntaxError:
        log.error(
            "SyntaxError, likely unbalanced brackets for parameter '%s', depth %s",
            name, depth,
        )
        raise SequenceEvaluationException(
            "SyntaxError evaluating sequence for parameter '{}', depth {}".format(name, depth)
        )
    except ValueError:
        log.error(
            "ValueError, likely wrong function argument for parameter '%s', depth %s",
            name, depth,
        )
        raise SequenceEvaluationException(
            "ValueError evaluating sequence for parameter '{}', depth {}".format(name, depth)
        )

    return numpy.array(result)


# ---------------------------------------------------------------------------
# get_sequence
# ---------------------------------------------------------------------------

def get_sequence(tree):
    """Convert a list-of-dicts *tree* into a flat list of parameter dicts.

    Each node in the tree has the form::

        {
            "parameter": "param_key",    # str – the procedure parameter name
            "sequence":  "linspace(0,1,10)",  # str – expression for eval_string
            "children":  [...]            # list of child nodes (may be empty)
        }

    The function evaluates every node's ``"sequence"`` string, computes the
    Cartesian product with its children (recursively), and returns a flat list
    where every element is a ``dict`` mapping parameter keys to scalar values.

    Example
    -------
    Given the tree::

        [
            {
                "parameter": "voltage",
                "sequence": "linspace(0, 1, 3)",
                "children": [
                    {"parameter": "current", "sequence": "range(2)", "children": []}
                ]
            }
        ]

    the result would be::

        [
            {"voltage": 0.0, "current": 0},
            {"voltage": 0.0, "current": 1},
            {"voltage": 0.5, "current": 0},
            {"voltage": 0.5, "current": 1},
            {"voltage": 1.0, "current": 0},
            {"voltage": 1.0, "current": 1},
        ]

    :param tree: List of root-level node dicts as described above.
    :returns: Flat list of parameter dicts, one per experiment run.
    :raises SequenceEvaluationException: When any sequence string cannot be
        evaluated.
    """
    result = []
    for node in tree:
        result.extend(_node_to_combinations(node, depth=0))
    return result


def _node_to_combinations(node, depth):
    """Recursively expand a single tree *node* into a list of parameter dicts.

    :param node: A dict with keys ``"parameter"``, ``"sequence"``, and
        ``"children"``.
    :param depth: Current depth in the tree, used for error messages.
    :returns: List of parameter dicts (one per value × child combination).
    """
    parameter = node["parameter"]
    sequence_str = node.get("sequence", "")
    children = node.get("children", [])

    values = eval_string(sequence_str, name=parameter, depth=depth)

    # Build child combinations (flat list of dicts) for the subtree rooted here
    child_combinations = []
    for child in children:
        child_combinations.extend(_node_to_combinations(child, depth=depth + 1))

    combinations = []
    if child_combinations:
        # Cartesian product: each value of this parameter paired with each
        # combination produced by the children
        for value, child_combo in product(values.tolist(), child_combinations):
            merged = {parameter: value}
            merged.update(child_combo)
            combinations.append(merged)
    else:
        # Leaf node – one dict per value
        for value in values.tolist():
            combinations.append({parameter: value})

    return combinations


# ---------------------------------------------------------------------------
# parse_sequence_file
# ---------------------------------------------------------------------------

def parse_sequence_file(content):
    """Parse the dash-indented text format used by the original sequencer.

    Each meaningful line has the form::

        - "Parameter Name", "sequence_expression"
        -- "Nested Param", "range(5)"

    The number of leading dashes determines the depth (1 dash = root,
    2 dashes = first level child, etc.).  Lines that do not match the
    pattern are silently ignored.

    :param content: The full text content of a sequence file as a ``str``
        (newlines included) or a list of line strings.

    :returns: A list of root-level node dicts ready to be passed to
        :func:`get_sequence`.  Each node has keys ``"parameter"``,
        ``"sequence"``, and ``"children"``.

    Example
    -------
    Given the file content::

        - "voltage", "linspace(0,1,5)"
        -- "current", "range(3)"

    the returned tree would be::

        [
            {
                "parameter": "voltage",
                "sequence": "linspace(0,1,5)",
                "children": [
                    {"parameter": "current", "sequence": "range(3)", "children": []}
                ]
            }
        ]
    """
    if isinstance(content, str):
        lines = content.splitlines()
    else:
        lines = list(content)

    # Pattern identical to the original sequencer_widget.py:
    #   (dashes) "parameter name", "sequence string"
    pattern = re.compile(r'([-]+)\s+"(.*?)"\s*,\s*"(.*?)"')

    # Parsed items as (depth, parameter, sequence) triples – depth is 0-based
    items = []
    for line in lines:
        line = line.strip()
        match = pattern.search(line)
        if not match:
            continue
        depth = len(match.group(1)) - 1  # 1 dash → depth 0 (root)
        if depth < 0:
            continue
        parameter = match.group(2)
        sequence = match.group(3)
        items.append((depth, parameter, sequence))

    if not items:
        return []

    # Convert flat (depth, param, seq) list into a tree of node dicts.
    # We maintain a stack of lists: stack[d] is the "children" list of the
    # most-recently-seen node at depth d-1 (or the top-level result list for d=0).
    root_nodes = []

    # stack[d] holds the children list into which nodes at depth d should be
    # appended.  Initialise with the root list at index 0.
    stack = [root_nodes]

    prev_depth = -1

    for depth, parameter, sequence in items:
        node = {"parameter": parameter, "sequence": sequence, "children": []}

        if depth == 0:
            # Root node: always goes into root_nodes
            root_nodes.append(node)
            # Reset the stack so that children of this root attach correctly
            stack = [root_nodes, node["children"]]

        elif depth > prev_depth:
            # Going deeper: attach to the children list of the last node
            # at the previous depth.  Extend the stack if necessary.
            while len(stack) <= depth:
                # The last entry in stack is the children list we are about to
                # populate; the node we want to nest under is the last element
                # of the list at depth-1.
                parent_children = stack[depth - 1]
                if parent_children:
                    stack.append(parent_children[-1]["children"])
                else:
                    # Edge-case: no parent node exists yet (malformed file);
                    # fall back to root.
                    stack.append(root_nodes)
            stack[depth].append(node)
            # Make this node's children list available at depth+1
            if len(stack) <= depth + 1:
                stack.append(node["children"])
            else:
                stack[depth + 1] = node["children"]

        else:
            # Same depth or shallower: trim the stack back and append
            # Truncate stack to depth+1 entries (children list at this depth)
            stack = stack[: depth + 1]
            # Ensure the children list for this depth is in the stack
            if len(stack) <= depth:
                stack.append(root_nodes)
            stack[depth].append(node)
            # Update children pointer for the next deeper level
            if len(stack) <= depth + 1:
                stack.append(node["children"])
            else:
                stack[depth + 1] = node["children"]

        prev_depth = depth

    return root_nodes
