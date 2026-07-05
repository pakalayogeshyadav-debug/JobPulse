import contextlib
import sys
import types

fcntl = types.ModuleType('fcntl')
fcntl.ioctl = lambda *args, **kwargs: None
fcntl.flock = lambda *args, **kwargs: None
fcntl.lockf = lambda *args, **kwargs: None
fcntl.LOCK_EX = 2; fcntl.LOCK_SH = 1; fcntl.LOCK_NB = 4; fcntl.LOCK_UN = 8
sys.modules['fcntl'] = fcntl

@contextlib.contextmanager
def mock_timeout(*args, **kwargs): yield
try:
    import airflow.utils.db
    airflow.utils.db.timeout_with_traceback = mock_timeout
except: pass
try:
    import airflow.dag_processing.importers.python_importer
    airflow.dag_processing.importers.python_importer._timeout = mock_timeout
except: pass

import runpy

runpy.run_module("airflow.__main__", run_name="__main__")
