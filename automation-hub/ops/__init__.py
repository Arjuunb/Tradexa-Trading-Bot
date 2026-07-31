"""Production runtime concerns: identity, logging, metrics, tracing, health.

Deliberately import-light. Everything here is pulled in by ``app.py`` during
boot, and several submodules touch optional third-party packages
(prometheus_client, the OpenTelemetry SDK) that must never be able to break
startup when absent. Import the submodule you need rather than relying on this
package to re-export it:

    from ops.runtime import role, runs_workers
    from ops.log import configure_logging, get_logger
    from ops.metrics import record_trade

Two naming decisions here exist to avoid shadowing the standard library, and
both were load-bearing rather than stylistic:

* The package is ``ops``, not ``platform``. ``app.py`` puts this directory on
  ``sys.path``, so a package named ``platform`` would shadow the stdlib module
  of that name for the entire process.

* The logging module is ``log.py``, not ``logging.py``. Running a script from
  inside this directory — ``python ops/backup_job.py``, which is exactly what
  the backup CronJob does — puts ``ops/`` itself at ``sys.path[0]``. A file
  called ``logging.py`` then shadows the stdlib ``logging`` for every module in
  the process, and the failure is a baffling "partially initialized module
  'logging' has no attribute 'Formatter'" at import time.
"""
