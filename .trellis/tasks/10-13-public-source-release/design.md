# Release Design

Work in a disposable filtered mirror and checkout. Preserve a verified private
Git recovery copy before rewriting remote branches/tags with expected-SHA guards.
Keep the user's database, environment, and excluded local directories untouched.

Remove earlier private implementations from mixed-use history, then restore only
reviewed current public files. Keep raw audit reports and recovery maps out of Git.
Use separate environments for US SQLAlchemy 2, CN SQLAlchemy 1.4/Python 3.11.3, and
the API App. A unified launcher and data redistribution are not part of this task.

Original product source uses MIT. Bundled Trellis tooling retains upstream AGPL-3.0;
reference archives and installed dependencies retain their own licenses.
