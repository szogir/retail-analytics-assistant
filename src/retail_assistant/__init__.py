"""Retail analytics assistant.

A small text-to-SQL assistant that answers business questions about a
synthetic discount-retail dataset. The package is organised around one idea:

    The language model only *proposes* a query. Deterministic code validates it,
    runs it with the asking user's permissions, and produces the numbers.

Planned modules (built step by step):

- ``llm``       - a provider-independent client interface and its adapters
- ``semantic``  - loads the semantic layer (metric definitions, join paths)
- ``sql``       - the safety validator and the permission-aware executor
- ``pipeline``  - wires the steps together: context -> SQL -> validate -> run -> answer
- ``cli``       - the command-line entry point
"""

__version__ = "0.1.0"
