"""Registry of the modules that declare evidence kinds.

Each later gate or tool module defines ``PRODUCES``, a tuple of kind names, and its task appends the
module's dotted name here.
"""

PRODUCER_MODULES: tuple = ("gates.tools.index",)
