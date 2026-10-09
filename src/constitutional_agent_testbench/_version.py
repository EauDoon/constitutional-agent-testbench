"""Single source of the package version.

pyproject.toml reads this value through [tool.setuptools.dynamic], the package
re-exports it as ``__version__``, and scripts/check_version.py compares the
changelog, release manifest and README against it. Edit the version only here.
Schema versions (policy, suite, report, receipt, replay, digest) are separate
and are not derived from it.
"""

__version__ = "0.5.19"
