"""Built-in TaskFamily profiles.

Importing this subpackage registers the chassis's first-party profiles
(``generic``, ``plan_doc_review``) against ``llm_client.workflow.duet_registry``.
Domain profiles live outside ``llm_client`` and register from their own
initialization code.

Order matters: ``generic`` registers first so the chassis default name is
always available before specialized profiles attempt to register.
"""

from llm_client.workflow.profiles import generic  # noqa: F401  (registers on import)
from llm_client.workflow.profiles import plan_doc_review  # noqa: F401
